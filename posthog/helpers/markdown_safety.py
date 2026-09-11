"""Defang externally-hosted URLs in LLM/markdown content before delivery to surfaces that auto-unfurl links.

Shared helper used across products. Injected/hallucinated URLs become inert code spans before reaching a
surface (e.g. Slack) that would auto-unfurl or linkify them; only PostHog hosts survive.
"""

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import re2

from posthog.api.utils import hostname_in_allowed_url_list

_ALLOWED_LINK_URLS = ["https://posthog.com", "https://*.posthog.com"]
# Match all CommonMark title forms (double/single-quoted, parenthesized) and allow whitespace before
# `)` (trailing `\s*`) — otherwise `[x](url "t")`, `[x](url 't')`, or `[x](url\n)` slip past this rule
# and the bare-URL rule (which skips `](`-prefixed URLs), reaching Slack un-defanged. Match ordinary
# destination characters as one atomic run. This removes the ambiguous nested repetition that makes
# malformed links backtrack, and it keeps no repeat state per destination character. Keep `[` out of
# the label as well, so a run of `[` cannot make the engine rescan the same suffix from every start.
# That drops the nested labels CommonMark rejects anyway, and `_ORPHAN_DEST_RE` still defangs them.
_MARKDOWN_LINK_RE = re.compile(
    r"\[([^\[\]]*)\]\(((?:(?>[^()\s]+)|\([^)]*\))+)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
)
_MARKDOWN_IMAGE_RE = re2.compile(r"!\[([^\]]*)\]\([^)]*\)")
# A malformed link the rule above can't span (e.g. `[x](url\nmore)`) leaves its URL after `](`, which
# the bare-URL rule skips — defang it here as a safety net.
_ORPHAN_DEST_RE = re.compile(r"\]\(((?:https?://|www\.)[^\s<>)\]`]+)", re.IGNORECASE)
# Spell out Python's Unicode whitespace semantics for RE2.
_PYTHON_WHITESPACE = r"\x09-\x0d\x1c-\x20\x85\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}"
_AUTOLINK_RE = re2.compile(r"(?i)<(https?://[^" + _PYTHON_WHITESPACE + r">]+)>")
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


def _replace_simple_links(source: str, pattern: Any, replace: Callable[[str, str], str]) -> str:
    # Unmatched openers must not rescan the suffix. Use RE2 offsets against the
    # original text so even isolated surrogate code points survive unchanged.
    matching_source = source.encode("utf-8", errors="replace").decode("utf-8")
    parts = []
    start = 0
    for match in pattern.finditer(matching_source):
        parts.append(source[start : match.start()])
        parts.append(replace(source[match.start() : match.end()], source[match.start(1) : match.end(1)]))
        start = match.end()
    parts.append(source[start:])
    return "".join(parts)


def strip_external_links_markdown(markdown: str) -> str:
    """Drop images, keep only PostHog links, and defang every other URL to a code span."""
    md = _replace_simple_links(markdown, _MARKDOWN_IMAGE_RE, lambda _whole, label: label)
    md = _MARKDOWN_LINK_RE.sub(
        lambda m: m.group(0) if _is_allowed_link_url(m.group(2)) else m.group(1),
        md,
    )
    # Backtick-wrap a non-PostHog orphan destination so the bare-URL rule's lookbehind keeps it inert.
    # Wrap only the URL, not the `](`/`)` — the source's own `)` balances it (appending one would dangle).
    md = _ORPHAN_DEST_RE.sub(lambda m: m.group(0) if _is_allowed_link_url(m.group(1)) else f"](`{m.group(1)}`", md)
    md = _replace_simple_links(md, _AUTOLINK_RE, lambda whole, url: _neutralize_url(url, keep_as=whole))
    md = _BARE_URL_RE.sub(lambda m: _neutralize_url(m.group(1)), md)
    return md
