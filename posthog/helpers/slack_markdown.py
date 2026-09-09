"""Building a Slack `markdown` block, which renders Markdown instead of Slack's own `mrkdwn`.

Shared by every surface that has Markdown to deliver, so the block's character budget is
stated in one place and cannot drift between them.
"""

from __future__ import annotations

# Slack budgets 12,000 characters across every markdown block in one message. A message carries
# one, and the headroom covers the blocks around it.
SLACK_MARKDOWN_TEXT_MAX_LEN = 11500


def truncate_slack_text(text: str, limit: int) -> str:
    """Keep text below the block's character limit with headroom."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def slack_markdown_block(text: str) -> dict:
    """The Slack block that renders Markdown."""
    return {"type": "markdown", "text": text}
