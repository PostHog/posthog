"""Convert between Comment content formats and Slack mrkdwn."""

import re


def content_to_slack_mrkdwn(content: str) -> str:
    """
    Convert plain text Comment content to Slack mrkdwn format.

    Currently handles plain text passthrough. Can be extended to support
    rich_content JSON -> Block Kit conversion in the future.
    """
    if not content:
        return ""

    # Escape Slack special characters that might cause unintended formatting
    # but preserve intentional markdown-like formatting
    text = content

    # Convert markdown-style bold **text** to Slack *text*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)

    # Convert markdown-style italic _text_ -- already valid in Slack mrkdwn

    # Convert markdown-style code `text` -- already valid in Slack mrkdwn

    # Convert markdown links [text](url) to Slack <url|text>
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", text)

    return text


def slack_mrkdwn_to_content(text: str) -> str:
    """
    Convert Slack mrkdwn to plain text for Comment storage.

    Strips Slack-specific formatting artifacts.
    """
    if not text:
        return ""

    # Convert Slack <url|text> links to plain text with URL
    text = re.sub(r"<([^|>]+)\|([^>]+)>", r"\2 (\1)", text)

    # Convert bare Slack <url> links
    text = re.sub(r"<([^>]+)>", r"\1", text)

    # Convert Slack bold *text* to plain **text** (markdown)
    # Be careful not to match multi-word patterns that span lines
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"**\1**", text)

    return text
