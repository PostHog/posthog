"""Delivering Markdown to Slack in a `markdown` block, which renders Markdown instead of Slack's
own `mrkdwn`.

Shared by every surface that has Markdown to deliver, so the block's character budget and the
rules its text must hold to are stated once rather than per product.
"""

from __future__ import annotations

import re

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
