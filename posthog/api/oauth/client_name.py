"""
Shared validation and HTML-safety helpers for OAuth client names.

Client names are untrusted input — they arrive from an unauthenticated DCR request body
(RFC 7591) or a partner-controlled CIMD metadata document — and surface on the OAuth
consent screen. Both ingestion paths (`dcr.py`, `cimd.py`) share these helpers.
"""

import re
import posixpath
import unicodedata
from urllib.parse import unquote, urlparse

from django.utils.html import escape

from rest_framework import serializers

# Blocked words in client names to prevent confusion attacks
# These prevent malicious apps from impersonating official PostHog applications
BLOCKED_CLIENT_NAME_PREFIXES = ["posthog"]  # Block names starting with these
BLOCKED_CLIENT_NAME_WORDS = ["official", "verified", "trusted"]  # Block names containing these

# AbstractApplication.name is a CharField(max_length=255). HTML-escaping can lengthen the
# value, so sanitize_client_name truncates the escaped result back to fit the column.
CLIENT_NAME_MAX_LENGTH = 255

# Matches a partial HTML entity left dangling at the end after truncation (e.g. "&am"
# from "&amp;"). After escaping, every literal "&" becomes the start of an entity, so any
# trailing "&" followed by entity-name characters without a closing ";" is a cut-off entity.
_DANGLING_ENTITY_RE = re.compile(r"&[a-zA-Z0-9#]*$")


POSTHOG_OWNED_DOMAINS = ("posthog.com", "posthog.net", "posthog.dev")

# Where customers control the response body on those domains: CDP webhook hosts, and the
# `/public/` routes CDP serves, which some environments expose on the app host itself.
CUSTOMER_CONTENT_HOST_LABELS = ("webhooks", "hooks")
CUSTOMER_CONTENT_PATH_PREFIXES = ("/public/",)

RESERVED_CLIENT_NAME = "posthog"

# Lm letters such as "ʼ" render as punctuation, and unassigned (Cn) code points can render as nothing.
_SKIPPED_CATEGORIES = frozenset({"Cc", "Cf", "Mn", "Me", "Lm", "Cn"})
_FORMAT_CATEGORY = "Cf"

# Hangul fillers and Egyptian blanks are letters by Unicode category, but they render as blank space.
_BLANK_LETTERS = frozenset({"ᅟ", "ᅠ", "ㅤ", "ﾠ", "\U00013441", "\U00013442"})

_ZERO_WIDTH_JOINER = "‍"

# Characters that render like a letter of "posthog" or of a blocked word, and that NFKD and casefold leave
# alone. Casefold maps Cherokee small letters to capitals, so the Cherokee keys are capitals.
_LETTER_LOOKALIKES = str.maketrans(
    {
        "0": "o",
        "о": "o",  # Cyrillic
        "ο": "o",  # Greek
        "օ": "o",  # Armenian
        "ⲟ": "o",  # Coptic
        "ᴏ": "o",
        "ø": "o",
        "ɵ": "o",
        "ꓳ": "o",  # Lisu
        "ⵔ": "o",  # Tifinagh
        "〇": "o",
        "ဝ": "o",  # Myanmar
        "٥": "o",  # Arabic-Indic five
        "۵": "o",  # Extended Arabic-Indic five
        "ഠ": "o",  # Malayalam
        "ଠ": "o",  # Oriya
        "ჿ": "o",  # Georgian
        "𐐬": "o",  # Deseret
        "θ": "o",  # Greek
        "ө": "o",  # Cyrillic
        "ѳ": "o",  # Cyrillic
        "р": "p",  # Cyrillic
        "ρ": "p",  # Greek
        "ⲣ": "p",  # Coptic
        "ᴘ": "p",
        "ᴩ": "p",
        "ƥ": "p",
        "ᵽ": "p",
        "ᵱ": "p",
        "Ꮲ": "p",  # Cherokee
        "ꓑ": "p",  # Lisu
        "ᑭ": "p",  # Canadian syllabics
        "ѕ": "s",  # Cyrillic
        "ꜱ": "s",
        "ʂ": "s",
        "Ꮪ": "s",  # Cherokee
        "ꓢ": "s",  # Lisu
        "т": "t",  # Cyrillic
        "τ": "t",  # Greek
        "ⲧ": "t",  # Coptic
        "ᴛ": "t",
        "ŧ": "t",
        "ƭ": "t",
        "ʈ": "t",
        "Ꭲ": "t",  # Cherokee
        "ꓔ": "t",  # Lisu
        "һ": "h",  # Cyrillic
        "н": "h",  # Cyrillic
        "η": "h",  # Greek
        "ⲏ": "h",  # Coptic
        "հ": "h",  # Armenian
        "ʜ": "h",
        "ħ": "h",
        "ɦ": "h",
        "Ꮒ": "h",  # Cherokee
        "Ꮋ": "h",  # Cherokee
        "ꓧ": "h",  # Lisu
        "ԍ": "g",  # Cyrillic
        "ց": "g",  # Armenian
        "ɡ": "g",
        "ɢ": "g",
        "ǥ": "g",
        "ɠ": "g",
        "ƍ": "g",
        "Ꮐ": "g",  # Cherokee
        "Ᏻ": "g",  # Cherokee
        "ꓖ": "g",  # Lisu
        "а": "a",  # Cyrillic
        "с": "c",  # Cyrillic
        "ԁ": "d",  # Cyrillic
        "е": "e",  # Cyrillic
        "і": "i",  # Cyrillic
        "ӏ": "l",  # Cyrillic
        "υ": "u",  # Greek
        "ս": "u",  # Armenian
        "ν": "v",  # Greek
        "ѵ": "v",  # Cyrillic
    }
)

_NEGATIVE_CIRCLED_A = 0x1F150
_NEGATIVE_SQUARED_A = 0x1F170
_REGIONAL_INDICATOR_A = 0x1F1E6

# Symbols that render like a letter of "posthog". They are punctuation too, so the checks read a name both ways.
_SYMBOL_LOOKALIKES = str.maketrans(
    {
        **{
            chr(block + ord(letter) - ord("a")): letter
            for block in (_NEGATIVE_CIRCLED_A, _NEGATIVE_SQUARED_A, _REGIONAL_INDICATOR_A)
            for letter in RESERVED_CLIENT_NAME
        },
        "○": "o",
        "◯": "o",
        "●": "o",
        "⬤": "o",
        "⭘": "o",
        "◉": "o",
        "◎": "o",
        "⊙": "o",
        "⏺": "o",
        "⭕": "o",
        "•": "o",
        "◦": "o",
        "∘": "o",
        "°": "o",
        "。": "o",
        "⚪": "o",
        "⚫": "o",
        "🔴": "o",
        "🔵": "o",
        "🟠": "o",
        "🟡": "o",
        "🟢": "o",
        "🟣": "o",
        "🟤": "o",
        "℗": "p",
        "⍴": "p",
        "⊤": "t",
    }
)


def _decomposed_without_marks(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if char.isspace() or (unicodedata.category(char) not in _SKIPPED_CATEGORIES and char not in _BLANK_LETTERS)
    )


def _skeleton(value: str) -> str:
    """Fold a client name into the form that the reserved-name checks compare.

    NFKD, not NFKC, because accents must stay decomposed so that the combining marks can be dropped.
    Marks are dropped before casefold too, because casefold turns some of them into letters (U+0345
    becomes "ι"). The second pass drops the marks that casefold produces.

    Look-alikes fold before digits do, because some digits render as a letter ("٥" reads as "o").
    The last pass folds the digits that read as letters, such as "0".
    """
    folded = _decomposed_without_marks(_decomposed_without_marks(value).casefold())

    kept: list[str] = []
    for char in folded:
        if char.isspace():
            kept.append(" ")
        elif ord(char) in _LETTER_LOOKALIKES:
            kept.append(char.translate(_LETTER_LOOKALIKES))
        elif unicodedata.decimal(char, None) is not None:
            kept.append(str(unicodedata.decimal(char)))
        else:
            kept.append(char)

    return " ".join("".join(kept).translate(_LETTER_LOOKALIKES).split())


def _readings(value: str) -> list[str]:
    """The skeleton with symbols dropped like punctuation, and with symbols read as the letters they resemble.

    "Post•Hog" spells "posthog" only in the first reading, and "P•stHog" only in the second.
    """
    skeleton = _skeleton(value)

    return [skeleton, skeleton.translate(_SYMBOL_LOOKALIKES)]


def _letters_and_digits(reading: str) -> str:
    """A reading without spaces or punctuation, so "Post Hog" and "Post-Hog" compare as "posthog".

    Letters from every script stay in place. Dropping non-Latin letters would make a name such as
    "Аналитика для PostHog" start with "posthog" and fail the DCR prefix rule.
    """
    return "".join(char for char in reading if char.isalnum())


def _without_leading_symbols(value: str) -> str:
    """Drop the symbols at the start of a name, so that "™PostHog" starts with "posthog" like "[PostHog]" does.

    NFKD expands some symbols into letters ("™" becomes "tm"), so this runs on the name before the fold.
    A symbol that reads as one letter, such as "Ⓟ" or "●", stays.
    """
    for index, char in enumerate(value):
        if char.isalnum() or len(_letters_and_digits(_skeleton(char).translate(_SYMBOL_LOOKALIKES))) == 1:
            return value[index:]

    return ""


def _reject_blocked_words(value: str) -> None:
    """Punctuation inside a word is dropped, so "Veri-fied" matches. Spaces stay, so "Trust Edition" doesn't."""
    for reading in _readings(value):
        words = "".join(char for char in reading if char.isalnum() or char == " ")
        for word in BLOCKED_CLIENT_NAME_WORDS:
            if word in words:
                raise serializers.ValidationError(f"Client name cannot contain '{word}'")


def validate_client_name(value: str) -> None:
    """Validate that a DCR client name doesn't impersonate official apps.

    Only the start of the name is reserved, because MCP clients name themselves after the server
    (for example "Claude Code (posthog)").

    DRF runs this validator before the field's `max_length` check, and the request is unauthenticated.
    A longer name returns at once and `max_length` rejects it, so the fold never runs on a large input.
    """
    if len(value) > CLIENT_NAME_MAX_LENGTH:
        return

    for reading in _readings(_without_leading_symbols(value)):
        for prefix in BLOCKED_CLIENT_NAME_PREFIXES:
            if _letters_and_digits(reading).startswith(prefix):
                raise serializers.ValidationError(f"Client name cannot start with '{prefix}'")

    _reject_blocked_words(value)


def is_posthog_controlled_url(url: str) -> bool:
    """Whether PostHog, not a customer, controls the document at `url`.

    A suffix match on our domains plus a denylist of customer-content hosts and paths. A new
    endpoint that serves customer-defined JSON on one of these domains must be added here.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if not any(host == domain or host.endswith(f".{domain}") for domain in POSTHOG_OWNED_DOMAINS):
        return False
    if host.split(".")[0] in CUSTOMER_CONTENT_HOST_LABELS:
        return False
    # Routers match paths case-insensitively and after decoding, so compare the same way.
    path = posixpath.normpath("/" + unquote(parsed.path).lower().lstrip("/"))
    return not any(f"{path}/".startswith(prefix) for prefix in CUSTOMER_CONTENT_PATH_PREFIXES)


def _mentions_posthog(value: str) -> bool:
    """Whether "posthog" appears with any other letters removed, as in "Post<letter>Hog".

    Only Latin letters and digits stay, because a substring check has no prefix rule to protect.
    """
    return any(
        RESERVED_CLIENT_NAME in "".join(char for char in _letters_and_digits(reading) if char.isascii())
        for reading in _readings(value)
    )


def validate_cimd_client_name(value: str, client_id: str) -> None:
    """Stricter than `validate_client_name`, for CIMD clients.

    "PostHog" is blocked anywhere in the name, including split forms like "Post Hog" and
    look-alike letters from other scripts. DCR keeps
    the starts-with rule, because MCP clients name themselves after the server (for example
    "Claude Code (posthog)").
    """
    # PostHog's own documents may use the name. The client_id is the URL PostHog fetched the
    # document from, so its location is proven. The error doesn't mention this exemption.
    if not is_posthog_controlled_url(client_id) and _mentions_posthog(value):
        raise serializers.ValidationError("Client name cannot contain 'PostHog'")

    _reject_blocked_words(value)


def sanitize_client_name(value: str) -> str:
    """HTML-escape an untrusted client name so it is safe to render in any sink.

    Escape at ingestion rather than trusting every downstream renderer to do it. The
    escaped result is truncated to the model's column limit because escaping can push
    it past 255 chars. Truncation can slice through an entity (e.g. leaving "&am" from
    "&amp;"), so any dangling partial entity at the end is stripped to avoid rendering
    a stray fragment.

    Format characters other than the zero-width joiner are dropped first, so the stored name
    renders its letters in the order the reserved-name checks read them. The joiner stays because
    emoji sequences need it.
    """
    visible = "".join(
        char for char in value if char == _ZERO_WIDTH_JOINER or unicodedata.category(char) != _FORMAT_CATEGORY
    )
    truncated = escape(visible.strip())[:CLIENT_NAME_MAX_LENGTH]
    undangled = _DANGLING_ENTITY_RE.sub("", truncated)

    return undangled
