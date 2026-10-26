"""Defang externally-hosted URLs in LLM/markdown content before delivery to surfaces that auto-unfurl links.

Shared helper used across products. Injected/hallucinated URLs become inert code spans before reaching a
surface (e.g. Slack) that would auto-unfurl or linkify them. Callers can opt named links into the
configured instance origin so self-hosted PostHog works without trusting report-supplied hosts.
"""

import re
from urllib.parse import urlparse

from markdown_it import MarkdownIt
from markdown_it.token import Token
from markdown_it.utils import EnvType

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
_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
# A malformed link the rule above can't span (e.g. `[x](url\nmore)`) leaves its URL after `](`, which
# the bare-URL rule skips — defang it here as a safety net.
_ORPHAN_DEST_RE = re.compile(r"\]\(((?:https?://|www\.)[^\s<>)\]`]+)", re.IGNORECASE)
_AUTOLINK_RE = re.compile(r"<(https?://[^\s>]+)>", re.IGNORECASE)
_BARE_URL_RE = re.compile(r"(?<!\]\()(?<![<`@])((?:https?://|www\.)[^\s<>)\]`]+)", re.IGNORECASE)


def is_allowed_link_url(url: str, additional_allowed_origin: str | None = None) -> bool:
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
    if additional_allowed_origin:
        try:
            origin = urlparse(additional_allowed_origin)
            if (parsed.scheme.lower(), host, parsed.port) == (
                origin.scheme.lower(),
                (origin.hostname or "").lower(),
                origin.port,
            ):
                return True
        except ValueError:
            return False
    return hostname_in_allowed_url_list(_ALLOWED_LINK_URLS, host)


def _neutralize_url(url: str, keep_as: str | None = None) -> str:
    check_url = url if url.lower().startswith(("http://", "https://")) else f"https://{url}"
    if is_allowed_link_url(check_url):
        return keep_as if keep_as is not None else url
    return f"`{url}`"


def _neutralize_bare_url(match: re.Match[str]) -> str:
    url = match.group(1)
    prefix = match.string[max(0, match.start() - 3) : match.start()]
    for marker in ("***", "___", "**", "__", "~~", "*", "_"):
        if prefix.endswith(marker):
            closing = url.rfind(marker)
            if closing > 0:
                suffix = _BARE_URL_RE.sub(lambda part: _neutralize_url(part.group(1)), url[closing:])
                return _neutralize_url(url[:closing]) + suffix
    return _neutralize_url(url)


def _strip_inline_links(markdown: str, additional_allowed_origin: str | None) -> str:
    md = _MARKDOWN_IMAGE_RE.sub(lambda m: m.group(1) or "", markdown)
    md = _MARKDOWN_LINK_RE.sub(
        lambda m: m.group(0) if is_allowed_link_url(m.group(2), additional_allowed_origin) else m.group(1),
        md,
    )
    # Backtick-wrap a non-PostHog orphan destination so the bare-URL rule's lookbehind keeps it inert.
    # Wrap only the URL, not the `](`/`)` — the source's own `)` balances it (appending one would dangle).
    md = _ORPHAN_DEST_RE.sub(
        lambda m: m.group(0) if is_allowed_link_url(m.group(1), additional_allowed_origin) else f"](`{m.group(1)}`",
        md,
    )
    md = _AUTOLINK_RE.sub(lambda m: _neutralize_url(m.group(1), keep_as=m.group(0)), md)
    md = _BARE_URL_RE.sub(_neutralize_bare_url, md)
    return md


def _literal_markdown(markdown: str) -> str:
    fence = "`" * max(3, max((len(run) + 1 for run in re.findall(r"`+", markdown)), default=3))
    return f"\n{fence}\n{markdown}\n{fence}\n\n"


def _is_unsafe_inline(token: Token, additional_allowed_origin: str | None) -> bool:
    return token.type == "image" or (
        token.type == "link_open"
        and not is_allowed_link_url(str(token.attrGet("href") or ""), additional_allowed_origin)
    )


def _validate_parsed_links(markdown: str, additional_allowed_origin: str | None) -> str:
    parser = MarkdownIt("commonmark", {"html": False})
    env: EnvType = {}
    parser.parse(markdown, env)
    lines = re.findall(r"[^\n]*\n|[^\n]+$", markdown)
    for reference in [*env.get("references", {}).values(), *env.get("duplicate_refs", [])]:
        if not is_allowed_link_url(reference["href"], additional_allowed_origin):
            start, end = reference["map"]
            lines[start:end] = ["\n"] * (end - start)
    markdown = "".join(lines)
    unsafe_ranges = sorted(
        {
            tuple(token.map)
            for token in parser.parse(markdown)
            if token.map is not None
            and any(_is_unsafe_inline(child, additional_allowed_origin) for child in token.children or [])
        }
    )
    if not unsafe_ranges:
        return markdown
    parts: list[str] = []
    cursor = 0
    for start, end in unsafe_ranges:
        if start < cursor:
            continue
        parts.append("".join(lines[cursor:start]))
        parts.append(_literal_markdown("".join(lines[start:end])))
        cursor = end
    parts.append("".join(lines[cursor:]))
    result = "".join(parts)
    if any(
        _is_unsafe_inline(child, additional_allowed_origin)
        for token in parser.parse(result)
        for child in token.children or []
    ):
        return _literal_markdown(markdown)
    return result


def strip_external_links_markdown(markdown: str, *, additional_allowed_origin: str | None = None) -> str:
    """The extra origin must come from trusted instance configuration, never report content."""
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    env: EnvType = {}
    MarkdownIt("commonmark", {"html": False}).parse(markdown, env)
    references = sorted(
        [*env.get("references", {}).values(), *env.get("duplicate_refs", [])],
        key=lambda reference: reference["map"][0],
    )
    lines = re.findall(r"[^\n]*\n|[^\n]+$", markdown)
    parts: list[str] = []
    cursor = 0
    for reference in references:
        start, end = reference["map"]
        parts.append(_strip_inline_links("".join(lines[cursor:start]), additional_allowed_origin))
        if is_allowed_link_url(reference["href"], additional_allowed_origin):
            parts.append("".join(lines[start:end]))
        else:
            parts.append("\n" * (end - start))
        cursor = end
    parts.append(_strip_inline_links("".join(lines[cursor:]), additional_allowed_origin))
    return _validate_parsed_links("".join(parts), additional_allowed_origin)
