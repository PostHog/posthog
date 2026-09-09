"""Building a Slack `markdown` block, which renders Markdown instead of Slack's own `mrkdwn`.

Shared by every surface that has Markdown to deliver, so the block's character budget is
stated once rather than per product.
"""

from __future__ import annotations

# Slack budgets 12,000 characters across every markdown block in one message. A message carries
# one, and the headroom covers the blocks around it.
SLACK_MARKDOWN_TEXT_MAX_LEN = 11500


def slack_markdown_block(text: str) -> dict:
    """The block Slack renders Markdown in. The caller is responsible for `text` being safe to
    show and within `SLACK_MARKDOWN_TEXT_MAX_LEN`, because Slack rejects the whole message
    otherwise."""
    return {"type": "markdown", "text": text}
