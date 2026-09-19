"""Post PostHog comment content into a Slack thread.

Token-agnostic: the caller supplies a ``slack_sdk.WebClient`` built from whichever workspace
bot token applies (the generic Slack ``Integration``, the conversations SupportHog bot, ...).
The inbound counterpart — ingesting Slack replies back as comments — is wired separately where
the Slack event webhook lives.
"""

from uuid import UUID

import structlog
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.web import SlackResponse

from posthog.comment.formatting import escape_slack_mrkdwn, rich_content_to_slack_payload
from posthog.helpers.slack_identity import resolve_slack_avatar_by_email
from posthog.helpers.slack_scopes import CHAT_WRITE_CUSTOMIZE_SCOPE

logger = structlog.get_logger(__name__)

# chat.postMessage fields that need the optional chat:write.customize scope.
_APPEARANCE_FIELDS = ("username", "icon_url")


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
    can_customize_appearance: bool = True,
) -> str | None:
    """Post a comment's content to a Slack channel, optionally threaded under ``thread_ts``.

    When ``item_url`` is given (the thread root), the message renders as a card linking back to the
    discussion; otherwise (replies) it's a plain threaded message. ``organization_id`` scopes
    @-mention resolution — without it every mention renders as a generic teammate. Returns the
    posted message's ``ts`` so the caller can anchor a mirror on the first post, or ``None`` when
    there was nothing to post. Raises on a Slack API failure so callers can react (the API action
    surfaces an error; the Celery tasks retry) instead of silently dropping the message.

    ``can_customize_appearance`` says whether the install granted ``chat:write.customize``. When it
    is False the message posts under the app's own name and icon. Callers that cannot tell may
    leave it True, because a refusal from Slack falls back to the same plain message.
    """
    slack_text, slack_blocks = rich_content_to_slack_payload(
        rich_content, content, include_images=False, organization_id=organization_id
    )
    if not slack_text.strip() and not slack_blocks:
        return None

    message_kwargs: dict = {
        "channel": channel,
        "text": slack_text,
    }
    if thread_ts:
        message_kwargs["thread_ts"] = thread_ts
    if can_customize_appearance:
        message_kwargs["username"] = author_name or "PostHog"
        # Show the author's Slack avatar when we can match them by email.
        icon_url = resolve_slack_avatar_by_email(client, author_email) if author_email else None
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
        response = _post_message(client, message_kwargs)
    except Exception as e:
        logger.warning("slack_thread_mirror_post_failed", channel=channel, thread_ts=thread_ts, error=str(e))
        raise
    return response.get("ts")


def _post_message(client: WebClient, message_kwargs: dict) -> SlackResponse:
    """Post the message, then post it again without the appearance fields if Slack refuses them.

    ``chat:write.customize`` is optional, so a workspace can install PostHog without it. Slack
    then rejects the whole call instead of ignoring ``username`` and ``icon_url``, and the comment
    is still worth delivering under the app's own name and icon.
    """
    try:
        return client.chat_postMessage(**message_kwargs)
    except SlackApiError as e:
        plain_kwargs = {key: value for key, value in message_kwargs.items() if key not in _APPEARANCE_FIELDS}
        if len(plain_kwargs) == len(message_kwargs) or not _refused_for_customize_scope(e):
            raise
        logger.info("slack_thread_mirror_appearance_scope_missing", channel=message_kwargs.get("channel"))
        return client.chat_postMessage(**plain_kwargs)


def _refused_for_customize_scope(error: SlackApiError) -> bool:
    """Whether Slack refused the call because the install lacks chat:write.customize."""
    response = error.response
    if response is None or response.get("error") != "missing_scope":
        return False
    # Slack names the scopes it wanted in ``needed``. Another missing scope cannot be fixed by
    # dropping the appearance fields, so retry only when this scope is named or none is.
    needed = response.get("needed")
    return needed is None or CHAT_WRITE_CUSTOMIZE_SCOPE in str(needed)
