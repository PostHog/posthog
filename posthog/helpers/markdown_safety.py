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
from posthog.slack.markdown import rendered_code_spans, slack_rich_text

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
_BARE_URL_RE = re.compile(r"(?<!\]\()((?:https?://|www\.)[^\s<>)\]`]+)", re.IGNORECASE)
# The same URL shape with no lookbehind: what the renderer drew is already past the question of
# which markdown rule the URL came from.
_ANY_URL_RE = re.compile(r"((?:https?://|www\.)[^\s<>)\]`]+)", re.IGNORECASE)


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


def _as_url(url: str) -> str:
    return url if url.lower().startswith(("http://", "https://")) else f"https://{url}"


def _neutralize_url(url: str, keep_as: str | None = None) -> str:
    check_url = _as_url(url)
    if is_allowed_link_url(check_url):
        return keep_as if keep_as is not None else url
    return f"`{url}`"


def _neutralize_trailing_emphasis(url: str, keep_as: str | None = None) -> str:
    """Wrap `url` without taking an emphasis marker that closes the text around it.

    The URL pattern accepts `*`, `_` and `~`, so a line like `*see https://host/x*` matches the
    closing marker as part of the URL. The wrapper would then close after that marker, the
    renderer would read the emphasis before the backticks, and the URL would be drawn as plain
    text that Slack linkifies.
    """
    core = url.rstrip("*_~")
    if not core:
        return url
    return _neutralize_url(core, keep_as) + url[len(core) :]


def _neutralize_bare_url(match: re.Match[str]) -> str:
    url = match.group(1)
    prefix = match.string[max(0, match.start() - 3) : match.start()]
    for marker in ("***", "___", "**", "__", "~~", "*", "_"):
        if prefix.endswith(marker):
            closing = url.rfind(marker)
            if closing > 0:
                suffix = _BARE_URL_RE.sub(lambda part: _neutralize_url(part.group(1)), url[closing:])
                return _neutralize_url(url[:closing]) + suffix
    return _neutralize_trailing_emphasis(url)


def _drop_stray_backticks(line: str) -> str:
    """Remove a backtick that opens no code span.

    The wrapper below adds backticks of its own. A stray one in front of a URL would pair with the
    wrapper's opening backtick instead, which leaves the closing backtick orphaned and the URL in
    plain text.
    """
    spans = rendered_code_spans(line)
    if not spans and "`" not in line:
        return line
    return "".join(
        character
        for index, character in enumerate(line)
        if character != "`" or any(start <= index < end for start, end in spans)
    )


def _renderer_draws_a_live_url(line: str) -> bool:
    """Whether the renderer still draws a defanged URL as ordinary text.

    Markdown pairing is not local: emphasis, brackets and backticks in the text around a URL can
    make the renderer close a span somewhere other than where the wrapper put it. Rather than
    chase each shape, ask the renderer what it produced.
    """
    pending: list[object] = [slack_rich_text(line, allowed_root="")]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            if node.get("type") == "text" and not node.get("style", {}).get("code"):
                if any(not is_allowed_link_url(_as_url(url)) for url in _ANY_URL_RE.findall(str(node.get("text", "")))):
                    return True
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    return False


def _redact_leaked_urls(line: str) -> str:
    """Drop the URLs from a line the renderer refuses to keep inert.

    Losing a URL from a hostile line is the acceptable outcome. Showing the recipient a live link
    written by an untrusted summary is not.
    """
    if not _renderer_draws_a_live_url(line):
        return line
    return _ANY_URL_RE.sub(
        lambda match: match.group(1) if is_allowed_link_url(_as_url(match.group(1))) else "(link removed)",
        line.replace("`", ""),
    )


def _neutralize_urls_outside_code(markdown: str) -> str:
    """Wrap every URL that the delivery renderer would draw as ordinary text.

    A URL already inside a code span is inert, and wrapping it again would split the span open and
    release it. Which regions count as code comes from the renderer, never from a second parser
    here: the two disagree on input the summary author controls, and the renderer is the one the
    recipient sees.
    """
    lines: list[str] = []
    for line in markdown.splitlines(keepends=True):
        line = _drop_stray_backticks(line)
        parts: list[str] = []
        cursor = 0
        for start, end in rendered_code_spans(line):
            parts.append(_BARE_URL_RE.sub(_neutralize_bare_url, line[cursor:start]))
            parts.append(line[start:end])
            cursor = end
        parts.append(_BARE_URL_RE.sub(_neutralize_bare_url, line[cursor:]))
        lines.append(_redact_leaked_urls("".join(parts)))
    return "".join(lines)


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
    md = _neutralize_urls_outside_code(md)
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
