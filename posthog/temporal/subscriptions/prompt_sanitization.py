from __future__ import annotations

import re
import unicodedata

INSIGHT_NAME_MAX_LEN = 120
INSIGHT_DESCRIPTION_MAX_LEN = 500
SERIES_LABEL_MAX_LEN = 200
SUBSCRIPTION_TITLE_MAX_LEN = 200
GENERIC_VALUE_MAX_LEN = 200
PROMPT_GUIDE_MAX_LEN = 500

_TAG_RE = re.compile(r"</?[a-zA-Z_][^>]*>")
_LLM_MARKER_RE = re.compile(
    r"</?\s*(?:system|user|assistant|human|insight_data|user_context|subscription_title)\b[^>]*>?",
    re.IGNORECASE,
)
_NEWLINE_RE = re.compile(r"[\r\n\u2028\u2029]+")
_WHITESPACE_RUN_RE = re.compile(r"[ \t]+")

_INVISIBLE_KEEP = {"\n", "\r", "\t"}
_EXTRA_INVISIBLES = (
    {"\u034f", "\u3164", "\uffa0"}
    | {chr(c) for c in range(0x115F, 0x1161)}
    | {chr(c) for c in range(0x17B4, 0x17B6)}
    | {chr(c) for c in range(0x180B, 0x180E)}
    | {chr(c) for c in range(0xFE00, 0xFE10)}
    | {chr(c) for c in range(0xE0100, 0xE01F0)}
)


def _is_invisible(c: str) -> bool:
    if c in _INVISIBLE_KEEP:
        return False
    if unicodedata.category(c) in ("Cc", "Cf"):
        return True
    return c in _EXTRA_INVISIBLES


def _strip_invisible(value: str) -> str:
    return "".join(c for c in value if not _is_invisible(c))


def sanitize_user_text(value: str | None, max_len: int) -> str:
    if not value:
        return ""
    cleaned = _strip_invisible(value)
    previous = ""
    while previous != cleaned:
        previous = cleaned
        cleaned = _LLM_MARKER_RE.sub("", cleaned)
        cleaned = _TAG_RE.sub("", cleaned)
    cleaned = _NEWLINE_RE.sub(" ", cleaned)
    cleaned = _WHITESPACE_RUN_RE.sub(" ", cleaned).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip()
    return cleaned
