def escape_slack_mrkdwn(text: str) -> str:
    """Escape Slack mrkdwn control characters in user-supplied text.

    Unescaped `<...>` sequences are live in mrkdwn: `<!channel>` broadcasts,
    `<@U…>` pings a user, and `<url|label>` renders a disguised link.
    """
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def channel_id_from_target(value: str) -> str:
    """Extract the Slack id from the frontend picker's `id|#name` or `id|@name` value.

    Slack API calls accept only the id. `chat.postMessage` accepts a member id as its `channel` and
    opens a direct message, so a member target resolves the same way as a channel target.
    """
    return value.split("|", 1)[0].strip()
