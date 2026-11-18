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


def validate_client_name(value: str) -> None:
    """Validate that client name doesn't impersonate official apps."""
    lower_value = value.lower()
    for prefix in BLOCKED_CLIENT_NAME_PREFIXES:
        if lower_value.startswith(prefix):
            raise serializers.ValidationError(f"Client name cannot start with '{prefix}'")
    for word in BLOCKED_CLIENT_NAME_WORDS:
        if word in lower_value:
            raise serializers.ValidationError(f"Client name cannot contain '{word}'")


POSTHOG_OWNED_DOMAINS = ("posthog.com", "posthog.net", "posthog.dev")

# Where customers control the response body on those domains: CDP webhook hosts, and the
# `/public/` routes CDP serves, which some environments expose on the app host itself.
CUSTOMER_CONTENT_HOST_LABELS = ("webhooks", "hooks")
CUSTOMER_CONTENT_PATH_PREFIXES = ("/public/",)

_NON_ALPHANUMERIC_RE = re.compile(r"[^a-z0-9]")

# Letters from other scripts that render like a letter of "posthog". NFKD already folds accents,
# full-width and mathematical forms, but not these, so "PоstHog" with a Cyrillic "о" would pass.
_POSTHOG_LOOKALIKES = str.maketrans(
    {
        "0": "o",
        "о": "o",
        "ο": "o",
        "օ": "o",
        "ᴏ": "o",
        "р": "p",
        "ρ": "p",
        "ᴘ": "p",
        "ѕ": "s",
        "ꜱ": "s",
        "т": "t",
        "τ": "t",
        "ᴛ": "t",
        "һ": "h",
        "н": "h",
        "η": "h",
        "ʜ": "h",
        "ɡ": "g",
        "ԍ": "g",
        "ɢ": "g",
    }
)


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
    folded = unicodedata.normalize("NFKD", value).casefold()
    folded = "".join(char for char in folded if not unicodedata.combining(char)).translate(_POSTHOG_LOOKALIKES)
    return "posthog" in _NON_ALPHANUMERIC_RE.sub("", folded)


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
    lower_value = value.lower()
    for word in BLOCKED_CLIENT_NAME_WORDS:
        if word in lower_value:
            raise serializers.ValidationError(f"Client name cannot contain '{word}'")


def sanitize_client_name(value: str) -> str:
    """HTML-escape an untrusted client name so it is safe to render in any sink.

    Escape at ingestion rather than trusting every downstream renderer to do it. The
    escaped result is truncated to the model's column limit because escaping can push
    it past 255 chars. Truncation can slice through an entity (e.g. leaving "&am" from
    "&amp;"), so any dangling partial entity at the end is stripped to avoid rendering
    a stray fragment.
    """
    truncated = escape(value)[:CLIENT_NAME_MAX_LENGTH]
    undangled = _DANGLING_ENTITY_RE.sub("", truncated)

    return undangled
