from __future__ import annotations

import re

# We only want to ignore responses that are *very* likely to be test/placeholder text
# or keyboard-smash gibberish. Be conservative: false positives hide real feedback.

_NORMALIZE_WHITESPACE_RE = re.compile(r"\s+")
_STRIP_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+")
_REPEATED_CHAR_RE = re.compile(r"^(.)\1{4,}$")  # 5+ of same char, e.g. "aaaaa"

# Common placeholder/test strings seen in feedback forms.
# Keep this list short and obvious.
_PLACEHOLDER_EXACT = {
    "test",
    "testing",
    "asdf",
    "asdfasdf",
    "qwer",
    "qwerty",
    "abc",
    "abcd",
    "123",
    "1234",
    "0000",
}

# Keyboard-walk fragments (lowercased, non-alnum stripped).
_KEYBOARD_FRAGMENTS = (
    "asdf",
    "qwer",
    "zxcv",
    "hjkl",
    "qwerty",
    "asdfgh",
    "12345",
)

_VOWELS = set("aeiou")


def _normalize(text: str) -> str:
    return _NORMALIZE_WHITESPACE_RE.sub(" ", text.strip().lower())


def should_ignore_survey_response(text: str) -> bool:
    """
    Returns True if the response is very likely to be placeholder/test or gibberish.

    This is intended for *filtering input to LLM summarization* (saving tokens and
    avoiding misleading summaries), not for dropping data at ingestion time.
    """

    normalized = _normalize(text)
    if not normalized:
        return True

    if normalized in _PLACEHOLDER_EXACT:
        return True

    # Pure punctuation / separators / emoji-only-ish inputs often sneak in.
    alnum = sum(1 for ch in normalized if ch.isalnum())
    if alnum == 0:
        return True

    if _REPEATED_CHAR_RE.match(normalized):
        return True

    compact = _STRIP_NON_ALNUM_RE.sub("", normalized)
    if compact in _PLACEHOLDER_EXACT:
        return True

    if compact and any(fragment in compact for fragment in _KEYBOARD_FRAGMENTS):
        # "asdf..." / "qwerty..." etc.
        return True

    # Heuristic for keyboard smash like "hjdashdjksahd":
    # - one token (no spaces)
    # - letters only
    # - medium length
    # - very low vowel ratio
    if " " not in normalized and normalized.isalpha() and normalized.isascii() and 10 <= len(normalized) <= 24:
        vowel_ratio = sum(1 for ch in normalized if ch in _VOWELS) / len(normalized)
        if vowel_ratio < 0.25:
            return True

    return False


def filter_survey_responses(responses: list[str]) -> list[str]:
    return [r for r in responses if not should_ignore_survey_response(r)]
