"""
File parsing for business_knowledge Stage 3.

Detects file types from content (magic bytes), not from HTTP headers or file
extensions alone. Enforces compressed + decompressed size caps. Delegates to
type-specific parsers that produce plain text suitable for the shared chunker.

Security notes:
- Compressed size is checked at the serializer layer before data reaches here.
- Magic-bytes detection prevents content-type spoofing (renaming a .exe to .pdf).
- ZIP-based formats (DOCX) are checked for decompressed size before parsing
  to guard against zip bombs.
- Encrypted PDFs are rejected with a clear error.
- pypdf and python-docx are imported lazily so the module loads fast when
  only text/URL sources are in use.
"""

from __future__ import annotations

import io
import os
import csv
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field

import structlog

from .facade.enums import MAX_FILE_DECOMPRESSED_BYTES, MAX_FILE_SIZE_BYTES

logger = structlog.get_logger(__name__)


class FileParseError(Exception):
    """User-safe error from file parsing."""


class UnsupportedFileTypeError(FileParseError):
    pass


class EncryptedPDFError(FileParseError):
    pass


class ZipBombError(FileParseError):
    pass


class FileTooLargeError(FileParseError):
    pass


ALLOWED_TYPES: dict[str, str] = {
    "application/pdf": "PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
    "text/markdown": "Markdown",
    "text/plain": "Plain text",
    "text/csv": "CSV",
}

MAX_CSV_ROWS = 10_000
MAX_PDF_PAGES = 2_000


@dataclass(frozen=True)
class ParsedFile:
    title: str
    content: str
    content_type: str
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_content_type(data: bytes, filename: str) -> str:
    """
    Detect content type from magic bytes first, then fall back to extension
    for text-based formats that lack distinctive magic bytes.
    """
    if data[:5] == b"%PDF-":
        return "application/pdf"

    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if "[Content_Types].xml" in zf.namelist():
                    ct = zf.read("[Content_Types].xml").decode("utf-8", errors="replace")
                    if "wordprocessingml" in ct:
                        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        except (zipfile.BadZipFile, KeyError, OSError):
            pass

    lower = os.path.basename(filename).lower()
    if lower.endswith((".md", ".markdown")):
        return "text/markdown"
    if lower.endswith(".csv"):
        return "text/csv"
    if lower.endswith(".txt"):
        return "text/plain"

    # Last resort: if it decodes as UTF-8, treat as plain text.
    try:
        data[:8192].decode("utf-8")
        return "text/plain"
    except UnicodeDecodeError:
        pass

    raise UnsupportedFileTypeError("Unsupported file type. Allowed: PDF, DOCX, Markdown (.md), CSV, plain text (.txt).")


# ---------------------------------------------------------------------------
# Security guards
# ---------------------------------------------------------------------------


def _check_zip_bomb(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            total = 0
            for info in zf.infolist():
                with zf.open(info) as f:
                    while chunk := f.read(65536):
                        total += len(chunk)
                        if total > MAX_FILE_DECOMPRESSED_BYTES:
                            raise ZipBombError(
                                f"Decompressed size exceeds the {MAX_FILE_DECOMPRESSED_BYTES // (1024 * 1024)} MB cap."
                            )
    except zipfile.BadZipFile:
        raise FileParseError("File appears corrupt — cannot read as ZIP.")


def sanitize_filename(filename: str) -> str:
    """Strip path components, null bytes; cap length."""
    name = filename.replace("\\", "/")
    name = os.path.basename(name)
    name = name.replace("\x00", "")
    return name[:255] if name else "unnamed"


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _parse_pdf(data: bytes, filename: str) -> ParsedFile:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as exc:
        raise FileParseError(f"Could not read PDF: {exc}")

    if reader.is_encrypted:
        raise EncryptedPDFError("Encrypted PDFs are not supported. Remove the password and re-upload.")

    if len(reader.pages) > MAX_PDF_PAGES:
        raise FileTooLargeError(
            f"PDF has {len(reader.pages):,} pages (cap is {MAX_PDF_PAGES:,}). Split it into smaller files."
        )

    pages: list[str] = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"[Page {i + 1}]\n{text.strip()}")

    content = "\n\n".join(pages)
    if not content.strip():
        raise FileParseError("PDF contains no extractable text (it may be scanned/image-only).")

    title = filename.rsplit(".", 1)[0] if "." in filename else filename
    return ParsedFile(
        title=title,
        content=content,
        content_type="application/pdf",
        metadata={"source_type": "file", "file_type": "pdf", "page_count": len(reader.pages)},
    )


def _parse_docx(data: bytes, filename: str) -> ParsedFile:
    _check_zip_bomb(data)

    from docx import Document
    from docx.opc.exceptions import PackageNotFoundError

    try:
        doc = Document(io.BytesIO(data))
    except PackageNotFoundError as exc:
        raise FileParseError(f"Could not read DOCX: {exc}")
    except (KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise FileParseError(f"Could not read DOCX: {exc}")

    parts: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style_name = (para.style.name or "").lower() if para.style else ""
        if "heading" in style_name:
            level = 1
            for ch in style_name:
                if ch.isdigit():
                    level = int(ch)
                    break
            parts.append(f"{'#' * level} {text}")
        else:
            parts.append(text)

    content = "\n\n".join(parts)
    if not content.strip():
        raise FileParseError("DOCX contains no extractable text.")

    title = filename.rsplit(".", 1)[0] if "." in filename else filename
    return ParsedFile(
        title=title,
        content=content,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        metadata={"source_type": "file", "file_type": "docx"},
    )


def _parse_markdown(data: bytes, filename: str) -> ParsedFile:
    text = data.decode("utf-8", errors="replace")
    if not text.strip():
        raise FileParseError("Markdown file is empty.")

    title = filename.rsplit(".", 1)[0] if "." in filename else filename
    return ParsedFile(
        title=title,
        content=text,
        content_type="text/markdown",
        metadata={"source_type": "file", "file_type": "markdown"},
    )


def _parse_txt(data: bytes, filename: str) -> ParsedFile:
    text = data.decode("utf-8", errors="replace")
    if not text.strip():
        raise FileParseError("Text file is empty.")

    title = filename.rsplit(".", 1)[0] if "." in filename else filename
    return ParsedFile(
        title=title,
        content=text,
        content_type="text/plain",
        metadata={"source_type": "file", "file_type": "txt"},
    )


def _parse_csv(data: bytes, filename: str) -> ParsedFile:
    text = data.decode("utf-8", errors="replace")
    if not text.strip():
        raise FileParseError("CSV file is empty.")

    try:
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise FileParseError("CSV has no header row.")

        rows: list[str] = []
        for i, row in enumerate(reader):
            if i >= MAX_CSV_ROWS:
                rows.append(f"[Truncated at {MAX_CSV_ROWS:,} rows]")
                break
            line_parts = [f"{k}: {v}" for k, v in row.items() if v]
            if line_parts:
                rows.append("\n".join(line_parts))
    except csv.Error as exc:
        raise FileParseError(f"Could not parse CSV: {exc}")

    content = "\n\n".join(rows)
    if not content.strip():
        raise FileParseError("CSV contains no data rows.")

    title = filename.rsplit(".", 1)[0] if "." in filename else filename
    return ParsedFile(
        title=title,
        content=content,
        content_type="text/csv",
        metadata={"source_type": "file", "file_type": "csv", "row_count": len(rows)},
    )


_PARSERS: dict[str, Callable[[bytes, str], ParsedFile]] = {
    "application/pdf": _parse_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": _parse_docx,
    "text/markdown": _parse_markdown,
    "text/plain": _parse_txt,
    "text/csv": _parse_csv,
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_file(data: bytes, filename: str) -> ParsedFile:
    """
    Detect file type and parse. Entry point for Stage 3 file ingestion.

    The caller (serializer) must enforce the compressed size cap before
    calling this function. This function enforces:
    - Content-type detection from magic bytes
    - Allowlist check
    - Decompressed size cap for ZIP-based formats
    - Type-specific parse errors (encrypted PDF, empty content)
    """
    if len(data) > MAX_FILE_SIZE_BYTES:
        raise FileTooLargeError(f"File exceeds the {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB cap.")

    content_type = detect_content_type(data, filename)
    if content_type not in ALLOWED_TYPES:
        raise UnsupportedFileTypeError(f"Unsupported file type. Allowed: {', '.join(ALLOWED_TYPES.values())}.")

    parser = _PARSERS[content_type]
    return parser(data, filename)
