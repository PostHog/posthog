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
"""

from __future__ import annotations

import io
import os
import csv
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field

import structlog
from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.table import Table as DocxTable
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .constants import MAX_FILE_DECOMPRESSED_BYTES, MAX_FILE_SIZE_BYTES

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
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            pass  # Not actually a zip — fall through to extension check
        else:
            with zf:
                _check_zip_bomb(zf)
                try:
                    if "[Content_Types].xml" in zf.namelist():
                        with zf.open("[Content_Types].xml") as ct_file:
                            ct = ct_file.read(4096).decode("utf-8", errors="replace")
                        if "wordprocessingml" in ct:
                            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                except (KeyError, OSError):
                    pass
                raise UnsupportedFileTypeError(
                    "Unsupported file type. Allowed: PDF, DOCX, Markdown (.md), CSV, plain text (.txt)."
                )

    lower = os.path.basename(filename).lower()
    if lower.endswith((".md", ".markdown")):
        return "text/markdown"
    if lower.endswith(".csv"):
        return "text/csv"
    if lower.endswith(".txt"):
        return "text/plain"

    # Last resort: if it decodes as UTF-8, treat as plain text.
    sample = data[:8192]
    try:
        sample.decode("utf-8")
        return "text/plain"
    except UnicodeDecodeError as exc:
        # Slicing may split a multibyte char at the boundary; if the only
        # error is "unexpected end of data" at the tail AND more data exists,
        # the full file is valid UTF-8.
        if exc.reason == "unexpected end of data" and len(data) > len(sample):
            return "text/plain"

    raise UnsupportedFileTypeError("Unsupported file type. Allowed: PDF, DOCX, Markdown (.md), CSV, plain text (.txt).")


# ---------------------------------------------------------------------------
# Security guards
# ---------------------------------------------------------------------------


def _check_zip_bomb(zf: zipfile.ZipFile) -> None:
    """Stream-check that decompressed size stays within cap.

    Accepts an already-opened ZipFile so the caller controls the
    BadZipFile boundary (non-zips that start with ``PK`` fall through
    to the extension check rather than hard-failing).
    """
    try:
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
        raise FileParseError("File appears corrupt — cannot read ZIP contents.")
    except (RuntimeError, NotImplementedError):
        raise FileParseError("File is encrypted or uses an unsupported compression method.")


def sanitize_filename(filename: str) -> str:
    """Strip path components, null bytes; cap length."""
    name = filename.replace("\\", "/")
    name = os.path.basename(name)
    name = name.replace("\x00", "")
    return name[:255] if name else "unnamed"


def _title_from_filename(filename: str) -> str:
    return filename.rsplit(".", 1)[0] if "." in filename else filename


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _parse_pdf(data: bytes, filename: str) -> ParsedFile:
    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as exc:
        raise FileParseError(f"Could not read PDF: {exc}")
    except Exception as exc:
        logger.warning("pdf_reader_unexpected_error", error=str(exc), exc_info=True)
        raise FileParseError(f"Could not read PDF: {exc}")

    if reader.is_encrypted:
        raise EncryptedPDFError("Encrypted PDFs are not supported. Remove the password and re-upload.")

    try:
        page_count = len(reader.pages)
    except Exception as exc:
        logger.warning("pdf_page_count_error", error=str(exc), exc_info=True)
        raise FileParseError(f"Could not read PDF: {exc}")

    if page_count > MAX_PDF_PAGES:
        raise FileTooLargeError(
            f"PDF has {page_count:,} pages (cap is {MAX_PDF_PAGES:,}). Split it into smaller files."
        )

    pages: list[str] = []
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            logger.warning("pdf_page_extract_error", page=i, exc_info=True)
            continue
        if text.strip():
            pages.append(f"[Page {i + 1}]\n{text.strip()}")

    content = "\n\n".join(pages)
    if not content.strip():
        raise FileParseError("PDF contains no extractable text (it may be scanned/image-only).")

    return ParsedFile(
        title=_title_from_filename(filename),
        content=content,
        content_type="application/pdf",
        metadata={"source_type": "file", "file_type": "pdf", "page_count": page_count},
    )


def _parse_docx(data: bytes, filename: str) -> ParsedFile:
    try:
        doc = Document(io.BytesIO(data))
    except PackageNotFoundError as exc:
        raise FileParseError(f"Could not read DOCX: {exc}")
    except (KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise FileParseError(f"Could not read DOCX: {exc}")

    parts: list[str] = []
    for block in doc.iter_inner_content():
        if isinstance(block, DocxTable):
            for row in block.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    parts.append(" | ".join(cells))
        else:
            text = block.text.strip()
            if not text:
                continue
            style_name = (block.style.name or "").lower() if block.style else ""
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

    return ParsedFile(
        title=_title_from_filename(filename),
        content=content,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        metadata={"source_type": "file", "file_type": "docx"},
    )


def _parse_markdown(data: bytes, filename: str) -> ParsedFile:
    text = data.decode("utf-8", errors="replace")
    if not text.strip():
        raise FileParseError("Markdown file is empty.")

    return ParsedFile(
        title=_title_from_filename(filename),
        content=text,
        content_type="text/markdown",
        metadata={"source_type": "file", "file_type": "markdown"},
    )


def _parse_txt(data: bytes, filename: str) -> ParsedFile:
    text = data.decode("utf-8", errors="replace")
    if not text.strip():
        raise FileParseError("Text file is empty.")

    return ParsedFile(
        title=_title_from_filename(filename),
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
        data_row_count = 0
        for i, row in enumerate(reader):
            if i >= MAX_CSV_ROWS:
                rows.append(f"[Truncated at {MAX_CSV_ROWS:,} rows]")
                break
            line_parts = [f"{k}: {v}" for k, v in row.items() if v]
            if line_parts:
                rows.append("\n".join(line_parts))
                data_row_count += 1
    except csv.Error as exc:
        raise FileParseError(f"Could not parse CSV: {exc}")

    content = "\n\n".join(rows)
    if not content.strip():
        raise FileParseError("CSV contains no data rows.")

    return ParsedFile(
        title=_title_from_filename(filename),
        content=content,
        content_type="text/csv",
        metadata={"source_type": "file", "file_type": "csv", "row_count": data_row_count},
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

    filename = sanitize_filename(filename)
    content_type = detect_content_type(data, filename)
    if content_type not in ALLOWED_TYPES:
        raise UnsupportedFileTypeError(f"Unsupported file type. Allowed: {', '.join(ALLOWED_TYPES.values())}.")

    parser = _PARSERS[content_type]
    return parser(data, filename)
