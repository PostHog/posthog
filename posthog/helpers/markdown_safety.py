"""Defang externally-hosted URLs in LLM/markdown content before delivery to surfaces that auto-unfurl links.

Shared helper used across products. Injected/hallucinated URLs become inert code spans before reaching a
surface (e.g. Slack) that would auto-unfurl or linkify them; only PostHog hosts survive.
"""

import re
from urllib.parse import urlparse

from posthog.api.utils import hostname_in_allowed_url_list

_ALLOWED_LINK_URLS = ["https://posthog.com", "https://*.posthog.com"]
# Match all CommonMark title forms (double/single-quoted, parenthesized) and allow whitespace before
# `)` (trailing `\s*`) — otherwise `[x](url "t")`, `[x](url 't')`, or `[x](url\n)` slip past this rule
# and the bare-URL rule (which skips `](`-prefixed URLs), reaching Slack un-defanged.
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\(((?:[^()\s]+|\([^)]*\))+)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)")
_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
# A malformed link the rule above can't span (e.g. `[x](url\nmore)`) leaves its URL after `](`, which
# the bare-URL rule skips — defang it here as a safety net.
_ORPHAN_DEST_RE = re.compile(r"\]\(((?:https?://|www\.)[^\s<>)\]`]+)", re.IGNORECASE)
_AUTOLINK_RE = re.compile(r"<(https?://[^\s>]+)>", re.IGNORECASE)
_BARE_URL_RE = re.compile(r"(?<!\]\()(?<![<`@])((?:https?://|www\.)[^\s<>)\]`]+)", re.IGNORECASE)


def _is_allowed_link_url(url: str) -> bool:
    if "\\" in url or any(c.isspace() or ord(c) < 0x20 for c in url):
        return False
    try:
        parsed = urlparse(url)
        if parsed.username is not None or parsed.password is not None:
            return False
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if parsed.scheme.lower() not in ("http", "https"):
        return False
    return hostname_in_allowed_url_list(_ALLOWED_LINK_URLS, host)


def _neutralize_url(url: str, keep_as: str | None = None) -> str:
    check_url = url if url.lower().startswith(("http://", "https://")) else f"https://{url}"
    if _is_allowed_link_url(check_url):
        return keep_as if keep_as is not None else url
    return f"`{url}`"


def strip_external_links_markdown(markdown: str) -> str:
    """Drop images, keep only PostHog links, and defang every other URL to a code span."""
    md = _MARKDOWN_IMAGE_RE.sub(lambda m: m.group(1) or "", markdown)
    md = _MARKDOWN_LINK_RE.sub(
        lambda m: m.group(0) if _is_allowed_link_url(m.group(2)) else m.group(1),
        md,
    )
    # Backtick-wrap a non-PostHog orphan destination so the bare-URL rule's lookbehind keeps it inert.
    # Wrap only the URL, not the `](`/`)` — the source's own `)` balances it (appending one would dangle).
    md = _ORPHAN_DEST_RE.sub(lambda m: m.group(0) if _is_allowed_link_url(m.group(1)) else f"](`{m.group(1)}`", md)
    md = _AUTOLINK_RE.sub(lambda m: _neutralize_url(m.group(1), keep_as=m.group(0)), md)
    md = _BARE_URL_RE.sub(lambda m: _neutralize_url(m.group(1)), md)
    return md
