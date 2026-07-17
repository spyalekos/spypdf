#!/usr/bin/env python3
"""
PDF Search & Replace Tool
Αναζήτηση και αντικατάσταση κειμένου σε PDF με διατήρηση μορφοποίησης.
Υποστηρίζει ελληνικά και unicode κείμενο.
"""

import flet as ft
import fitz  # PyMuPDF
import os
import re
import asyncio
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class CharInfo:
    """Ένας χαρακτήρας με θέση και στυλ."""
    char: str
    bbox: tuple
    origin: tuple
    font: str
    size: float
    color: int
    flags: int
    page_num: int


@dataclass
class Match:
    """Εύρημα αναζήτησης."""
    chars: List[CharInfo]
    matched_text: str
    page_num: int


class PDFProcessor:
    """Επεξεργασία PDF: αναζήτηση + αντικατάσταση σε επίπεδο χαρακτήρων."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.doc = fitz.open(filepath)

    def close(self):
        self.doc.close()

    def _get_page_chars(self, page_num: int) -> List[CharInfo]:
        page = self.doc[page_num]
        chars = []
        blocks = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    font = span.get("font", "Helvetica")
                    size = span.get("size", 12.0)
                    color = span.get("color", 0)
                    flags = span.get("flags", 0)
                    for ch in span.get("chars", []):
                        c = ch.get("c", "")
                        if not c:
                            continue
                        chars.append(CharInfo(
                            char=c,
                            bbox=tuple(ch["bbox"]),
                            origin=tuple(ch["origin"]),
                            font=font,
                            size=size,
                            color=color,
                            flags=flags,
                            page_num=page_num,
                        ))
        return chars

    def find_matches(self, search_text: str, case_sensitive: bool = False) -> List[Match]:
        if not search_text:
            return []
        matches = []
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.escape(search_text)

        for page_num in range(len(self.doc)):
            chars = self._get_page_chars(page_num)
            if not chars:
                continue
            full_text = "".join(c.char for c in chars)
            for m in re.finditer(pattern, full_text, flags):
                matches.append(Match(
                    chars=chars[m.start():m.end()],
                    matched_text=m.group(),
                    page_num=page_num,
                ))
        return matches

    def count_occurrences(self, search_text: str, case_sensitive: bool = False) -> int:
        return len(self.find_matches(search_text, case_sensitive))

    def _pick_fontname(self, original_font: str, flags: int) -> str:
        fn = original_font.lower()
        is_bold = bool(flags & (1 << 4)) or "bold" in fn
        is_italic = bool(flags & (1 << 1)) or "italic" in fn or "oblique" in fn

        if "courier" in fn or "mono" in fn:
            if is_bold and is_italic: return "cobi"
            if is_bold: return "cobo"
            if is_italic: return "coit"
            return "cour"
        if "times" in fn or "roman" in fn or "serif" in fn:
            if is_bold and is_italic: return "tibi"
            if is_bold: return "tibo"
            if is_italic: return "tiit"
            return "tiro"
        # Helvetica family (default)
        if is_bold and is_italic: return "hebi"
        if is_bold: return "hebo"
        if is_italic: return "heit"
        return "helv"

    def _replace_match(self, match: Match, replacement_text: str) -> None:
        if not match.chars:
            return

        page = self.doc[match.page_num]
        ref = match.chars[0]

        x0 = min(c.bbox[0] for c in match.chars)
        y0 = min(c.bbox[1] for c in match.chars)
        x1 = max(c.bbox[2] for c in match.chars)
        y1 = max(c.bbox[3] for c in match.chars)
        available_width = x1 - x0

        ci = ref.color
        color = (((ci >> 16) & 0xFF) / 255.0,
                 ((ci >> 8) & 0xFF) / 255.0,
                 (ci & 0xFF) / 255.0)

        font_size = ref.size
        
        # Check if replacement text has Greek/Unicode characters
        has_unicode = any(ord(ch) > 127 for ch in replacement_text)
        fontfile = None
        
        if has_unicode:
            # Arial TTF fonts mapping for Greek support on Windows
            is_bold = bool(ref.flags & (1 << 4)) or "bold" in ref.font.lower()
            is_italic = bool(ref.flags & (1 << 1)) or "italic" in ref.font.lower() or "oblique" in ref.font.lower()
            
            if is_bold and is_italic:
                target_file = "C:/Windows/Fonts/arialbi.ttf"
                target_name = "arial-bolditalic"
            elif is_bold:
                target_file = "C:/Windows/Fonts/arialbd.ttf"
                target_name = "arial-bold"
            elif is_italic:
                target_file = "C:/Windows/Fonts/ariali.ttf"
                target_name = "arial-italic"
            else:
                target_file = "C:/Windows/Fonts/arial.ttf"
                target_name = "arial"
                
            if os.path.exists(target_file):
                fontfile = target_file
                fontname = target_name
            else:
                if os.path.exists("C:/Windows/Fonts/arial.ttf"):
                    fontfile = "C:/Windows/Fonts/arial.ttf"
                    fontname = "arial"
                else:
                    fontname = self._pick_fontname(ref.font, ref.flags)
        else:
            fontname = self._pick_fontname(ref.font, ref.flags)

        try:
            font_obj = fitz.Font(fontname=fontname, fontfile=fontfile)
        except Exception:
            font_obj = fitz.Font(fontname="helv")
            fontname = "helv"
            fontfile = None

        new_width = font_obj.text_length(replacement_text, fontsize=font_size)
        final_text = replacement_text

        if new_width > available_width and available_width > 2:
            font_size = max(font_size * (available_width / new_width) * 0.97, 3.5)
        elif new_width < available_width:
            space_w = font_obj.text_length(" ", fontsize=font_size)
            if space_w > 0:
                n = int((available_width - new_width) / space_w)
                final_text = replacement_text + " " * n

        # Κάλυψη παλιού κειμένου
        page.draw_rect(
            fitz.Rect(x0 - 0.5, y0 - 0.5, x1 + 0.5, y1 + 1.0),
            color=(1, 1, 1), fill=(1, 1, 1)
        )

        origin_x = ref.bbox[0]
        origin_y = ref.origin[1]

        try:
            page.insert_text((origin_x, origin_y), final_text,
                             fontname=fontname, fontfile=fontfile, fontsize=font_size, color=color)
        except Exception:
            try:
                page.insert_text((origin_x, origin_y), final_text,
                                 fontname="helv", fontsize=font_size, color=color)
            except Exception as e:
                print(f"[!] insert_text σφάλμα: {e}")

    def replace_all(self, search_text: str, replacement_text: str,
                    case_sensitive: bool = False, progress_callback=None) -> int:
        matches = self.find_matches(search_text, case_sensitive)
        total = len(matches)
        if total == 0:
            return 0
        for i, match in enumerate(reversed(matches)):
            self._replace_match(match, replacement_text)
            if progress_callback:
                progress_callback(i + 1, total)
        return total

    def save_as(self, output_path: str) -> None:
        self.doc.save(output_path, garbage=4, deflate=True)


# ══════════════════════════════════════════════════════════════════
#  GUI (Flet)
# ══════════════════════════════════════════════════════════════════

class AppState:
    def __init__(self):
        self.processor: Optional[PDFProcessor] = None
        self.pending_save: bool = False


def make_card(title: str, controls: list) -> ft.Container:
    return ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(title, size=14, weight="bold", color="#e2e8f0"),
                    ],
                    alignment=ft.MainAxisAlignment.START,
                ),
                ft.Divider(height=1, color="#334155"),
                *controls,
            ],
            spacing=12,
        ),
        bgcolor="#1e293b",
        border_radius=12,
        border=ft.Border.all(color="#334155", width=1),
        padding=ft.Padding(16, 16, 16, 16),
        margin=ft.Margin(0, 0, 0, 12),
    )


async def main(page: ft.Page):
    state = AppState()

    page.title = "PDF Search & Replace v1.3.6"
    page.window.width = 760
    page.window.height = 990
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = ft.Theme(color_scheme_seed="#4f46e5")
    page.bgcolor = "#0f172a"
    page.scroll = ft.ScrollMode.AUTO

    # Helper dialogs
    def show_alert_dialog(title: str, message: str):
        def close_dialog(e):
            page.pop_dialog()
            page.update()
        dlg = ft.AlertDialog(
            title=ft.Text(title, weight="bold", color="#e2e8f0"),
            content=ft.Text(message, color="#cbd5e1"),
            bgcolor="#1e293b",
            actions=[
                ft.TextButton("OK", on_click=close_dialog)
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.show_dialog(dlg)
        page.update()

    async def ask_yes_no(title: str, message: str) -> bool:
        fut = asyncio.Future()
        def on_yes(e):
            page.pop_dialog()
            page.update()
            fut.set_result(True)
        def on_no(e):
            page.pop_dialog()
            page.update()
            fut.set_result(False)
        dlg = ft.AlertDialog(
            title=ft.Text(title, weight="bold", color="#e2e8f0"),
            content=ft.Text(message, color="#cbd5e1"),
            bgcolor="#1e293b",
            modal=True,
            actions=[
                ft.TextButton("Ναι", on_click=on_yes),
                ft.TextButton("Όχι", on_click=on_no),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.show_dialog(dlg)
        page.update()
        return await fut

    # FilePicker
    file_picker = ft.FilePicker()
    page.services.append(file_picker)

    # UI Controls definition
    pdf_path_field = ft.TextField(
        label="Διαδρομή αρχείου PDF",
        read_only=True,
        expand=True,
        text_size=13,
        border_color="#334155",
        focused_border_color="#6366f1",
        label_style=ft.TextStyle(color="#94a3b8"),
    )
    open_btn = ft.Button(
        content="Άνοιγμα…",
        icon=ft.Icons.FOLDER_OPEN,
    )
    
    search_field = ft.TextField(
        label="Αναζήτηση",
        expand=True,
        text_size=13,
        border_color="#334155",
        focused_border_color="#6366f1",
        label_style=ft.TextStyle(color="#94a3b8"),
    )
    replace_field = ft.TextField(
        label="Αντικατάσταση",
        expand=True,
        text_size=13,
        border_color="#334155",
        focused_border_color="#6366f1",
        label_style=ft.TextStyle(color="#94a3b8"),
    )
    case_checkbox = ft.Checkbox(
        label="Διάκριση πεζών/κεφαλαίων (case-sensitive)",
        value=False,
    )

    count_btn = ft.Button(
        content="🔢 Καταμέτρηση εμφανίσεων",
    )
    replace_all_btn = ft.Button(
        content="⚡ Αντικατάσταση Όλων",
        bgcolor="#4f46e5",
        color="white",
    )

    output_path_field = ft.TextField(
        label="Αρχείο εξόδου",
        read_only=True,
        expand=True,
        text_size=13,
        border_color="#334155",
        focused_border_color="#6366f1",
        label_style=ft.TextStyle(color="#94a3b8"),
    )
    choose_out_btn = ft.Button(
        content="Επιλογή…",
        icon=ft.Icons.SAVE_AS,
    )
    save_btn = ft.Button(
        content="💾 Αποθήκευση",
        bgcolor="#4f46e5",
        color="white",
    )

    progress_bar = ft.ProgressBar(value=0.0, height=6, color="#4f46e5", bgcolor="#334155")
    log_field = ft.TextField(
        value="Φόρτωσε ένα αρχείο PDF για να ξεκινήσεις.\n",
        multiline=True,
        read_only=True,
        bgcolor="#0f172a",
        color="#cbd5e1",
        text_size=11,
        text_style=ft.TextStyle(font_family="Consolas"),
        min_lines=4,
        max_lines=5,
        border_color="#334155",
    )

    status_text = ft.Text("Έτοιμο.", color="#94a3b8", size=12)

    # Log helper
    def log_message(msg: str):
        log_field.value = (log_field.value or "") + msg + "\n"
        page.update()

    # Validate inputs
    def validate() -> bool:
        if not state.processor:
            show_alert_dialog("Προσοχή", "Δεν έχει φορτωθεί αρχείο PDF.")
            return False
        if not search_field.value:
            show_alert_dialog("Προσοχή", "Το πεδίο αναζήτησης είναι κενό.")
            return False
        return True

    # Event handlers
    async def open_file(e):
        res = await file_picker.pick_files(
            dialog_title="Επιλογή αρχείου PDF",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["pdf"],
        )
        if not res or len(res) == 0:
            return
        
        path = res[0].path
        if not path:
            return
            
        try:
            if state.processor:
                state.processor.close()
            state.processor = PDFProcessor(path)
            pdf_path_field.value = path
            
            base, ext = os.path.splitext(path)
            output_path_field.value = base + "_modified" + ext
            
            pages = len(state.processor.doc)
            log_message(f"✅ Φορτώθηκε: {os.path.basename(path)}  ({pages} σελίδες)")
            status_text.value = f"Ανοιχτό: {os.path.basename(path)} — {pages} σελίδες"
            state.pending_save = False
            progress_bar.value = 0.0
        except Exception as err:
            show_alert_dialog("Σφάλμα", f"Αποτυχία ανοίγματος:\n{err}")
        
        page.update()

    async def choose_output(e):
        initial = output_path_field.value or pdf_path_field.value
        res = await file_picker.save_file(
            dialog_title="Αποθήκευση ως…",
            file_name=os.path.basename(initial) if initial else "output.pdf",
            allowed_extensions=["pdf"],
        )
        if res:
            output_path_field.value = res
            page.update()

    async def run_count(e):
        if not validate():
            return
        status_text.value = "Καταμέτρηση…"
        page.update()
        
        search = search_field.value
        case = case_checkbox.value
        
        def sync_worker():
            try:
                return state.processor.count_occurrences(search, case), None
            except Exception as err:
                return 0, str(err)
                
        loop = asyncio.get_running_loop()
        n, err = await loop.run_in_executor(None, sync_worker)
        
        if err:
            show_alert_dialog("Σφάλμα", err)
            status_text.value = "Σφάλμα!"
        else:
            msg = f"Βρέθηκαν {n} εμφανίσεις του «{search}»"
            log_message(f"🔍 {msg}")
            status_text.value = msg
            show_alert_dialog("Αποτέλεσμα αναζήτησης", msg)
            
        page.update()

    async def run_replace(e):
        if not validate():
            return
        
        search = search_field.value
        replace = replace_field.value
        case = case_checkbox.value
        
        try:
            state.processor.close()
            state.processor = PDFProcessor(pdf_path_field.value)
        except Exception as err:
            show_alert_dialog("Σφάλμα", f"Επαναφόρτωση απέτυχε:\n{err}")
            return
        
        progress_bar.value = 0.0
        log_message(f"\n🔄 Αναζήτηση: «{search}»  →  Αντικατάσταση: «{replace}»")
        status_text.value = "Επεξεργασία…"
        page.update()
        
        def sync_worker():
            def prog_cb(done, total):
                progress_bar.value = done / total if total else 1.0
                status_text.value = f"Αντικατάσταση {done}/{total}…"
                page.update()
                
            try:
                n = state.processor.replace_all(search, replace, case, prog_cb)
                return n, None
            except Exception as err:
                return 0, str(err)
        
        # Disable buttons during execution
        replace_all_btn.disabled = True
        count_btn.disabled = True
        open_btn.disabled = True
        choose_out_btn.disabled = True
        save_btn.disabled = True
        page.update()
        
        loop = asyncio.get_running_loop()
        n, err = await loop.run_in_executor(None, sync_worker)
        
        # Re-enable buttons
        replace_all_btn.disabled = False
        count_btn.disabled = False
        open_btn.disabled = False
        choose_out_btn.disabled = False
        save_btn.disabled = False
        
        if err:
            show_alert_dialog("Σφάλμα", err)
            status_text.value = "Σφάλμα!"
        else:
            progress_bar.value = 1.0
            if n > 0:
                msg = f"✅ Αντικαταστάθηκαν {n} εμφανίσεις."
                state.pending_save = True
                show_alert_dialog("Επιτυχία", 
                                  f"Αντικαταστάθηκαν {n} εμφανίσεις.\n\n"
                                  "Πάτα «Αποθήκευση» για να αποθηκεύσεις το αρχείο.")
            else:
                msg = f"Δεν βρέθηκε «{search}»."
                show_alert_dialog("Αποτέλεσμα", f"Δεν βρέθηκε «{search}» στο PDF.")
            log_message(msg)
            status_text.value = msg
            
        page.update()

    async def save_file_handler(e):
        if not state.processor:
            show_alert_dialog("Προσοχή", "Δεν έχει φορτωθεί αρχείο PDF.")
            return
        out = output_path_field.value
        if not out:
            show_alert_dialog("Προσοχή", "Ορίστε αρχείο εξόδου.")
            return
            
        if os.path.abspath(out) == os.path.abspath(pdf_path_field.value):
            confirm = await ask_yes_no(
                "Επιβεβαίωση", 
                "Θα αντικατασταθεί το αρχικό αρχείο. Συνέχεια;"
            )
            if not confirm:
                return
                
        try:
            state.processor.save_as(out)
            log_message(f"💾 Αποθηκεύτηκε: {out}")
            status_text.value = f"Αποθηκεύτηκε: {os.path.basename(out)}"
            state.pending_save = False
            show_alert_dialog("Αποθηκεύτηκε", f"Το αρχείο αποθηκεύτηκε:\n{out}")
        except Exception as err:
            show_alert_dialog("Σφάλμα αποθήκευσης", str(err))
            
        page.update()

    async def exit_app(e):
        if state.processor:
            try:
                state.processor.close()
            except Exception:
                pass
        try:
            await page.window.close()
        except Exception:
            pass

    # Bind handlers to buttons
    open_btn.on_click = open_file
    choose_out_btn.on_click = choose_output
    save_btn.on_click = save_file_handler
    count_btn.on_click = run_count
    replace_all_btn.on_click = run_replace
    
    # Enter key triggers run_replace
    search_field.on_submit = run_replace
    replace_field.on_submit = run_replace

    def show_help(e):
        print("show_help clicked!", flush=True)
        help_text = (
            "1. Επιλογή PDF: Πατήστε «Άνοιγμα...» και επιλέξτε το PDF αρχείο.\n\n"
            "2. Αναζήτηση: Συμπληρώστε το κείμενο που θέλετε να βρείτε.\n\n"
            "3. Αντικατάσταση: Συμπληρώστε το νέο κείμενο.\n\n"
            "4. Επιλογές: Επιλέξτε «Διάκριση πεζών/κεφαλαίων» αν απαιτείται.\n\n"
            "5. Καταμέτρηση: Δείτε το σύνολο των εμφανίσεων πατώντας «Καταμέτρηση εμφανίσεων».\n\n"
            "6. Αντικατάσταση Όλων: Αντικαταστήστε το κείμενο διατηρώντας τη μορφοποίηση.\n\n"
            "7. Αποθήκευση: Ορίστε το αρχείο εξόδου και πατήστε «Αποθήκευση»."
        )
        
        help_content = ft.Column(
            [
                ft.Text(help_text, color="#cbd5e1", size=13),
                ft.Divider(color="#334155"),
                ft.Row(
                    [
                        ft.Text("Δημιουργός:", color="#94a3b8", size=12),
                        ft.TextButton(
                            content=ft.Text("SpyAlekos", color="#6366f1", size=12, weight="bold"),
                            url="https://github.com/spyalekos",
                        )
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=2,
                )
            ],
            tight=True,
            spacing=10,
        )
        
        def close_help(e):
            page.pop_dialog()
            page.update()
            
        help_dlg = ft.AlertDialog(
            title=ft.Text("Οδηγίες Χρήσης", weight="bold", color="#e2e8f0"),
            content=help_content,
            bgcolor="#1e293b",
            actions=[
                ft.TextButton("Κλείσιμο", on_click=close_help)
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.show_dialog(help_dlg)
        page.update()

    # Exit button in header
    exit_btn = ft.ElevatedButton(
        content="Έξοδος",
        icon=ft.Icons.EXIT_TO_APP,
        color="white",
        bgcolor="#b91c1c",
    )
    exit_btn.on_click = exit_app

    # Help button in header
    help_btn = ft.ElevatedButton(
        content="Βοήθεια",
        icon=ft.Icons.HELP_OUTLINE,
        color="white",
        bgcolor="#4f46e5",
    )
    help_btn.on_click = show_help

    # Header Control
    header = ft.Container(
        content=ft.Row(
            [
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Icon(icon=ft.Icons.FIND_REPLACE, color="white", size=28),
                                ft.Text("PDF Search & Replace v1.3.6", size=20, weight="bold", color="white"),
                            ],
                            spacing=10,
                        ),
                        ft.Text(
                            "Αναζήτηση & Αντικατάσταση με διατήρηση μορφοποίησης  |  Υποστήριξη ελληνικών",
                            size=12,
                            color="#cbd5e1",
                        )
                    ],
                    spacing=4,
                    expand=True,
                ),
                ft.Row(
                    [
                        help_btn,
                        exit_btn,
                    ],
                    spacing=8,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        gradient=ft.LinearGradient(
            begin=ft.Alignment(-1, -1),
            end=ft.Alignment(1, 1),
            colors=["#1e1b4b", "#312e81"]
        ),
        padding=ft.Padding(16, 14, 16, 14),
    )

    # Status Bar
    status_bar = ft.Container(
        content=status_text,
        bgcolor="#1e293b",
        padding=ft.Padding(12, 6, 12, 6),
        border=ft.Border(top=ft.BorderSide(width=1, color="#334155")),
    )

    # Construct the cards
    card_input = make_card("📄 Αρχείο PDF εισόδου", [
        ft.Row([pdf_path_field, open_btn], spacing=10)
    ])
    
    card_sr = make_card("🔎 Αναζήτηση & Αντικατάσταση", [
        ft.Row([search_field, replace_field], spacing=10),
        case_checkbox,
        ft.Row([count_btn, replace_all_btn], spacing=10),
    ])
    
    card_output = make_card("💾 Αρχείο εξόδου", [
        ft.Row([output_path_field, choose_out_btn, save_btn], spacing=10)
    ])
    
    card_log = make_card("📋 Καταγραφή & Πρόοδος", [
        progress_bar,
        log_field,
    ])

    body = ft.Container(
        content=ft.Column(
            [
                card_input,
                card_sr,
                card_output,
                card_log,
            ],
            spacing=10,
        ),
        padding=ft.Padding(16, 16, 16, 16),
    )

    # Add components to page
    page.add(
        header,
        body,
        status_bar,
    )

    # Force initial draw
    page.update()

    # Close PyInstaller Splash Screen if active
    try:
        import pyi_splash
        pyi_splash.close()
    except ImportError:
        pass


if __name__ == "__main__":
    ft.run(main)
