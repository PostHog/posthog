"""Post PostHog comment content into a Slack thread.

Token-agnostic: the caller supplies a ``slack_sdk.WebClient`` built from whichever workspace
bot token applies (the generic Slack ``Integration``, the conversations SupportHog bot, ...).
The inbound counterpart — ingesting Slack replies back as comments — is wired separately where
the Slack event webhook lives.
"""

from uuid import UUID

import structlog
from slack_sdk import WebClient

from posthog.comment.formatting import escape_slack_mrkdwn, rich_content_to_slack_payload
from posthog.helpers.slack_identity import resolve_slack_avatar_by_email

logger = structlog.get_logger(__name__)


def slack_author_from_user(user: object | None) -> tuple[str, str]:
    """Resolve a comment author to (display_name, email) for the Slack post.

    ``user`` is a ``User`` (typed loosely to avoid importing the model here). Falls back to a
    neutral "PostHog" name with no email for system/AI-authored comments.
    """
    if user is not None:
        name = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip() or getattr(
            user, "email", ""
        )
        return name or "PostHog", getattr(user, "email", "") or ""
    return "PostHog", ""


def _mrkdwn_safe_url(url: str) -> str:
    """Percent-encode the characters that terminate or split a mrkdwn ``<url|label>`` link."""
    return url.replace("<", "%3C").replace(">", "%3E").replace("|", "%7C")


SLACK_SECTION_TEXT_LIMIT = 3000


def _quote_mrkdwn(body: str) -> str:
    """Prefix every line so multi-line bodies render fully inside the quote, not just line one."""
    return "> " + body.replace("\n", "\n> ")


def _discussion_card_blocks(*, body_mrkdwn: str, author_name: str, item_url: str, item_label: str) -> list[dict]:
    """A Block Kit card for the thread root: 'New comment on <link>' with the PostHog logo, the
    quoted comment body, an 'Open in PostHog' button, and a reply-to-sync hint. Replies stay plain
    text since they're threaded under it.
    """
    heading = f"New comment on <{_mrkdwn_safe_url(item_url)}|{escape_slack_mrkdwn(item_label)}> in PostHog:\n\n"
    quoted_body = _quote_mrkdwn(body_mrkdwn or "_(no text)_")
    # The heading and body share one section, so the body's budget is whatever the heading leaves
    # of Slack's per-section text limit. Truncated content is still reachable via the button.
    body_budget = SLACK_SECTION_TEXT_LIMIT - len(heading)
    if len(quoted_body) > body_budget:
        quoted_body = quoted_body[: body_budget - 1] + "…"
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": heading + quoted_body},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "image",
                    "image_url": "https://us.posthog.com/static/icons/android-chrome-192x192.png",
                    "alt_text": "PostHog",
                },
                {"type": "mrkdwn", "text": "Replies to this thread will sync to PostHog"},
            ],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open in PostHog", "emoji": True},
                    "url": item_url,
                }
            ],
        },
    ]


def post_comment_to_slack_thread(
    *,
    client: WebClient,
    channel: str,
    content: str,
    rich_content: dict | None,
    author_name: str,
    author_email: str = "",
    thread_ts: str | None = None,
    item_url: str | None = None,
    item_label: str | None = None,
    organization_id: str | UUID | None = None,
) -> str | None:
    """Post a comment's content to a Slack channel, optionally threaded under ``thread_ts``.

    When ``item_url`` is given (the thread root), the message renders as a card linking back to the
    discussion; otherwise (replies) it's a plain threaded message. ``organization_id`` scopes
    @-mention resolution — without it every mention renders as a generic teammate. Returns the
    posted message's ``ts`` so the caller can anchor a mirror on the first post, or ``None`` when
    there was nothing to post. Raises on a Slack API failure so callers can react (the API action
    surfaces an error; the Celery tasks retry) instead of silently dropping the message.
    """
    slack_text, slack_blocks = rich_content_to_slack_payload(
        rich_content, content, include_images=False, organization_id=organization_id
    )
    if not slack_text.strip() and not slack_blocks:
        return None

    # Show the author's Slack avatar when we can match them by email (needs chat:write.customize).
    icon_url = resolve_slack_avatar_by_email(client, author_email) if author_email else None

    message_kwargs: dict = {
        "channel": channel,
        "text": slack_text,
        "username": author_name or "PostHog",
    }
    if thread_ts:
        message_kwargs["thread_ts"] = thread_ts
    if icon_url:
        message_kwargs["icon_url"] = icon_url

    if item_url:
        message_kwargs["blocks"] = _discussion_card_blocks(
            body_mrkdwn=slack_text,
            author_name=author_name,
            item_url=item_url,
            item_label=item_label or "the discussion",
        )
        # text stays as the plain body for notification previews / fallback clients.
    elif slack_blocks:
        message_kwargs["blocks"] = slack_blocks

    try:
        response = client.chat_postMessage(**message_kwargs)
    except Exception as e:
        logger.warning("slack_thread_mirror_post_failed", channel=channel, thread_ts=thread_ts, error=str(e))
        raise
    return response.get("ts")
