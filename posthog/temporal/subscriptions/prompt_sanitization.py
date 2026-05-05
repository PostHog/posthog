from __future__ import annotations

import re

INSIGHT_NAME_MAX_LEN = 120
INSIGHT_DESCRIPTION_MAX_LEN = 500
SERIES_LABEL_MAX_LEN = 200
SUBSCRIPTION_TITLE_MAX_LEN = 200
GENERIC_VALUE_MAX_LEN = 200
PROMPT_GUIDE_MAX_LEN = 500

_TAG_RE = re.compile(r"</?[a-zA-Z_][^>]*>")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x85]")
_DANGEROUS_UNICODE_RE = re.compile("[\u200b-\u200f\u2028-\u202f\u2060-\u206f\ufeff]")
_NEWLINE_RE = re.compile(r"[\r\n]+")
_WHITESPACE_RUN_RE = re.compile(r"[ \t]+")


def sanitize_user_text(value: str | None, max_len: int) -> str:
    if not value:
        return ""
    cleaned = _CONTROL_RE.sub("", value)
    cleaned = _DANGEROUS_UNICODE_RE.sub("", cleaned)
    previous = ""
    while previous != cleaned:
        previous = cleaned
        cleaned = _TAG_RE.sub("", cleaned)
    cleaned = _NEWLINE_RE.sub(" ", cleaned)
    cleaned = _WHITESPACE_RUN_RE.sub(" ", cleaned).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip()
    return cleaned
