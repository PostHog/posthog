"""
Shared validation and HTML-safety helpers for OAuth client names.

Client names are untrusted input — they arrive from an unauthenticated DCR request body
(RFC 7591) or a partner-controlled CIMD metadata document — and surface on the OAuth
consent screen. Both ingestion paths (`dcr.py`, `cimd.py`) share these helpers.
"""

import re

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
