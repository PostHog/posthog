"""Flatten an HTML email part into the text the inbox stores.

Two inbound shapes arrive without usable text. A Gmail message can be HTML-only,
with no `text/plain` part at all. A sender can also put a whole HTML document *in*
the `text/plain` part, and Mailgun passes that through as `body-plain`. The inbox
renders message text as Markdown, so an unflattened document reaches the reader as
escaped tags and indented code blocks instead of prose.

`recover_links_from_html` folds the hyperlinks back in after the flattening, so the
reader keeps the links the markup carried.
"""

from __future__ import annotations

import re
from html import unescape

from django.utils.html import strip_tags

from bs4 import BeautifulSoup, NavigableString, PageElement, Tag

from posthog.dataclasses import frozen

_HTML_PARAGRAPH_TAGS = frozenset({"blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "ol", "p", "table", "ul"})
_HTML_LINE_TAGS = frozenset({"div", "li", "tr"})
_HTML_SKIPPED_TAGS = frozenset({"head", "script", "style", "title"})
_HTML_WHITESPACE_RE = re.compile(r"\s+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_PREFORMATTED_PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")
# A text part that opens with a doctype or an `<html>` tag is a document, not prose.
# The test stays this narrow on purpose: a support email often quotes markup, and
# flattening prose that merely contains tags would drop what the customer wanted to show.
_HTML_DOCUMENT_START_RE = re.compile(
    r"[\s﻿]*(?:<\?xml[^>]*>\s*)?(?:<!doctype\s+html|<html[\s>])",
    re.IGNORECASE,
)


def looks_like_html_document(text: str) -> bool:
    """Report whether a text part holds an HTML document instead of prose."""
    return bool(_HTML_DOCUMENT_START_RE.match(text))


def html_to_text(html: str) -> str:
    """Flatten an HTML-only body to plain text, keeping paragraph and line breaks.

    `strip_tags` joins adjacent blocks with no separator, so `<p>a.</p><p>b</p>`
    becomes `a.b`. Links are folded back in later by `recover_links_from_html`.
    """
    preformatted: list[str] = []
    try:
        text = _flatten_html(BeautifulSoup(html, "html.parser"), preformatted)
    except Exception:  # noqa: BLE001 — a malformed HTML part must never fail ingestion
        preformatted = []
        text = unescape(strip_tags(html))
    lines = (line.strip() for line in text.split("\n"))
    text = _BLANK_LINES_RE.sub("\n\n", "\n".join(lines)).strip()
    # Preformatted blocks go back in after the cleanup, so their indentation survives.
    return _PREFORMATTED_PLACEHOLDER_RE.sub(lambda match: _get_preformatted_block(preformatted, match), text)


@frozen
class _HtmlSeparator:
    text: str


def _flatten_html(soup: BeautifulSoup, preformatted: list[str]) -> str:
    """Emit the text of `soup` in one pass, replacing each top-level `<pre>` with a placeholder.

    The walk reads the tree without modifying it, because BeautifulSoup locates a
    node among its siblings with a linear scan on every insert or replace, which
    makes per-node edits quadratic on an email with many sibling elements.
    """
    parts: list[str] = []
    stack: list[PageElement | _HtmlSeparator] = list(reversed(soup.contents))
    while stack:
        node = stack.pop()
        if isinstance(node, _HtmlSeparator):
            parts.append(node.text)
        elif isinstance(node, NavigableString):
            if type(node) is NavigableString:
                parts.append(_HTML_WHITESPACE_RE.sub(" ", node).replace("\0", ""))
        elif isinstance(node, Tag) and node.name not in _HTML_SKIPPED_TAGS:
            if node.name == "br":
                parts.append("\n")
            elif node.name == "pre":
                preformatted.append(_preformatted_text(node))
                parts.append(f"\0{len(preformatted) - 1}\0\n\n")
            else:
                if node.name in _HTML_PARAGRAPH_TAGS:
                    stack.append(_HtmlSeparator(text="\n\n"))
                elif node.name in _HTML_LINE_TAGS:
                    stack.append(_HtmlSeparator(text="\n"))
                stack.extend(reversed(node.contents))
    return "".join(parts)


def _preformatted_text(pre: Tag) -> str:
    parts: list[str] = []
    for node in pre.descendants:
        if type(node) is NavigableString:
            parts.append(node.replace("\0", ""))
        elif isinstance(node, Tag) and node.name == "br":
            parts.append("\n")
    return "".join(parts).strip("\n")


def _get_preformatted_block(preformatted: list[str], match: re.Match[str]) -> str:
    index = int(match.group(1))
    return preformatted[index] if index < len(preformatted) else ""
