"""Delivering Markdown to Slack in a `markdown` block, which renders Markdown instead of Slack's
own `mrkdwn`.

Shared by every surface that has Markdown to deliver, so the block's character budget and the
rules its text must hold to are stated once rather than per product.
"""

from __future__ import annotations

import re
from typing import Any

from markdown_it import MarkdownIt

# Slack budgets 12,000 characters across every markdown block in one message. A message carries
# one, and the headroom covers the blocks around it.
SLACK_MARKDOWN_TEXT_MAX_LEN = 11500

# The constructs Markdown reads only at the start of a line: an ATX heading, a list item, a block
# quote, a fence, a table row, and a thematic break. A list item and a heading need the space that
# separates the marker from the content, which is what keeps `**Bold**` and `#hashtag` out.
_LINE_ANCHORED_OPENING = re.compile(
    r"""
    \#{1,6}(\s|$)               # heading
    |[-*+]\s                    # bullet list item
    |\d{1,9}[.)]\s              # ordered list item
    |>                          # block quote
    |```|~~~                    # fenced code
    |\|                         # table row
    |(-\s*){3,}$|(\*\s*){3,}$|(_\s*){3,}$   # thematic break
    """,
    re.VERBOSE,
)


def opens_with_line_anchored_markdown(text: str) -> bool:
    """Whether the first line of `text` is a construct Markdown reads only at the start of a line.

    Such a line takes no prefix: anything put in front of it moves the marker off the line start,
    and Slack then renders the markup as literal text instead of the heading, list, or quote it
    stands for. Text that opens with a paragraph has no such constraint.
    """
    first_line = text.partition("\n")[0]
    # An indented code block opens on four spaces or a tab. Up to three leading spaces still count
    # as the start of the line for every other construct.
    if first_line.startswith(("    ", "\t")):
        return True
    return bool(_LINE_ANCHORED_OPENING.match(first_line.lstrip(" ")))


def slack_markdown_block(text: str) -> dict:
    """The block Slack renders Markdown in. The caller is responsible for `text` being safe to
    show and within `SLACK_MARKDOWN_TEXT_MAX_LEN`, because Slack rejects the whole message
    otherwise."""
    return {"type": "markdown", "text": text}


_INLINE_MARKUP = re.compile(
    r"(?P<link>\[[^\[\]\n]*\]\((?:[^()\s]|\([^)]*\))+\))|"
    r"<u>(?P<underline>[\s\S]+?)</u>|(?P<bold_marker>\*{1,2})(?P<bold>[^*\n]+)(?P=bold_marker)|"
    r"(?<!\w)_(?P<italic>[^_\n]+)_(?!\w)|~(?P<strike>[^~\n]+)~|`(?P<code>[^`\n]+)`"
)


def _inline_elements(text: str, style: dict[str, bool], allowed_root: str) -> list[dict[str, Any]]:
    # Deferred: markdown_safety pulls in posthog.api.utils, which is too heavy for the django.setup() path.
    from posthog.helpers.markdown_safety import is_allowed_link_url

    elements: list[dict[str, Any]] = []
    cursor = 0
    for match in _INLINE_MARKUP.finditer(text):
        if match.start() > cursor:
            elements.append({"type": "text", "text": text[cursor : match.start()], "style": style})
        if match.group("link") is not None:
            tokens = MarkdownIt("commonmark", {"html": False}).parseInline(match.group("link"))[0].children or []
            destination = next((str(token.attrGet("href")) for token in tokens if token.type == "link_open"), "")
            label = "".join(token.content for token in tokens if token.type in {"text", "code_inline"})
            if is_allowed_link_url(destination, allowed_root):
                elements.append({"type": "link", "url": destination, "text": label, "style": style})
            else:
                elements.append({"type": "text", "text": label, "style": style})
        for name in ("bold", "italic", "underline", "strike", "code"):
            content = match.group(name)
            if content is not None:
                nested_style = {**style, name: True}
                if name == "code":
                    elements.append({"type": "text", "text": content, "style": nested_style})
                else:
                    elements.extend(_inline_elements(content, nested_style, allowed_root))
                break
        cursor = match.end()
    if cursor < len(text):
        elements.append({"type": "text", "text": text[cursor:], "style": style})
    return elements


def slack_rich_text(summary: str, *, allowed_root: str) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    for line in summary.splitlines():
        line = line.strip()
        if not line:
            if elements and elements[-1]["type"] == "rich_text_list":
                elements.append({"type": "rich_text_section", "elements": [{"type": "text", "text": "\n"}]})
            continue
        bullet = re.match(r"^(?:[•*-]\s+|(\d+)[.)]\s+)(.+)$", line)
        content = line
        if bullet:
            content = bullet.group(2)
        section = {"type": "rich_text_section", "elements": _inline_elements(content, {}, allowed_root)}
        if bullet:
            list_style = "ordered" if bullet.group(1) else "bullet"
            if elements and elements[-1]["type"] == "rich_text_list" and elements[-1]["style"] == list_style:
                elements[-1]["elements"].append(section)
            else:
                elements.append({"type": "rich_text_list", "style": list_style, "elements": [section]})
        else:
            elements.append(section)
    return {"type": "rich_text", "elements": elements}
