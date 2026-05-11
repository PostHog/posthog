"""URL helpers used by the tracked HTTP transport.

`scrub_url` redacts auth-bearing query parameters before a URL is logged
or written into a captured sample. Path is preserved verbatim — query
values for matching keys are replaced with `REDACTED`.

`url_template` returns a low-cardinality variant where path segments that
look like IDs are replaced with `{id}`. We don't use it for log fields any
more (the user asked for full URLs in logs) but still emit it alongside
so that aggregation queries against the log_entries table have a stable
group-by.
"""

from __future__ import annotations

import re
from typing import Final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_REDACT_PARAM_NAMES: Final[frozenset[str]] = frozenset(
    {
        # Generic auth/secret param names
        "api_key",
        "apikey",
        "access_token",
        "auth",
        "auth_token",
        "key",
        "password",
        "secret",
        "sig",
        "signature",
        "token",
        # OAuth 2.0 / token-exchange flow params (RFC 6749 / RFC 7521 / OIDC).
        # These are usually sent in form bodies but can also appear in URLs;
        # we cover them here so the same denylist serves both `scrub_url` and
        # the form-urlencoded body scrubber in `sampling.py`.
        "client_secret",
        "client_assertion",
        "client_assertion_type",
        "code",
        "code_verifier",
        "id_token",
        "id_token_hint",
        "refresh_token",
        "subject_token",
        "actor_token",
    }
)

_REDACTED: Final[str] = "REDACTED"

_NUMERIC_ID = re.compile(r"^\d+$")
_UUID_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_HEX_ID = re.compile(r"^[0-9a-fA-F]{16,}$")


def scrub_url(url: str) -> str:
    """Return `url` with auth-bearing query-param values replaced by REDACTED.

    Param names are matched case-insensitively against `_REDACT_PARAM_NAMES`.
    Order, encoding, and unrelated params are preserved.
    """
    try:
        parts = urlsplit(url)
    except Exception:
        return url

    if not parts.query:
        return url

    pairs = parse_qsl(parts.query, keep_blank_values=True)
    scrubbed = [(name, _REDACTED if name.lower() in _REDACT_PARAM_NAMES else value) for name, value in pairs]
    new_query = urlencode(scrubbed, doseq=False)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def url_template(url: str) -> str:
    """Return a low-cardinality version of `url` for log grouping.

    Segments that look like numeric IDs, UUIDs, or long hex tokens are
    replaced with `{id}`. The query string is dropped entirely (logs already
    capture the scrubbed full URL alongside).
    """
    try:
        parts = urlsplit(url)
    except Exception:
        return url

    segments = parts.path.split("/")
    rewritten = [_template_segment(s) for s in segments]
    return urlunsplit((parts.scheme, parts.netloc, "/".join(rewritten), "", ""))


def _template_segment(segment: str) -> str:
    if not segment:
        return segment
    if _NUMERIC_ID.match(segment) or _UUID_ID.match(segment) or _HEX_ID.match(segment):
        return "{id}"
    return segment


def host_of(url: str) -> str:
    try:
        return urlsplit(url).netloc or "unknown"
    except Exception:
        return "unknown"
