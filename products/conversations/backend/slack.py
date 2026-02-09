"""
Slack inbound handler for the support/conversations product.

Handles three triggers that create or update tickets from Slack:
1. Dedicated channel: messages in a configured support channel
2. Bot mention: @mention the bot to create a ticket
3. Emoji reaction: react with a configurable emoji to create a ticket from a message

All three converge to create_or_update_slack_ticket().
"""

import re

from django.conf import settings

import structlog
from slack_sdk import WebClient

from posthog.models.comment import Comment
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.team.team import Team

from .models import Ticket
from .models.constants import Channel, Status

logger = structlog.get_logger(__name__)


def get_slack_client(team: Team, integration: Integration | None = None) -> WebClient:
    """
    Get a Slack WebClient for the team.

    Tries to use the bot token from conversations_settings first (SupportHog),
    falls back to Integration model (legacy PostHog Slack app).
    """
    settings_dict = team.conversations_settings or {}
    bot_token = settings_dict.get("slack_bot_token")

    if bot_token:
        return WebClient(token=bot_token)

    if integration:
        slack = SlackIntegration(integration)
        return slack.client

    raise ValueError("No Slack credentials available for this team")


def resolve_slack_user(client: WebClient, slack_user_id: str) -> dict:
    """Resolve a Slack user ID to name, email, and avatar."""
    try:
        user_info = client.users_info(user=slack_user_id)
        profile = user_info.get("user", {}).get("profile", {})
        return {
            "name": profile.get("display_name") or profile.get("real_name") or "Unknown",
            "email": profile.get("email"),
            "avatar": profile.get("image_72"),  # 72x72 avatar URL
        }
    except Exception:
        logger.warning("slack_support_user_resolve_failed", slack_user_id=slack_user_id)
        return {"name": "Unknown", "email": None, "avatar": None}


def clean_slack_text(text: str) -> str:
    """Strip Slack formatting artifacts like <@U123> mentions and <url|label> links."""
    # Replace <@USER_ID> with @user
    text = re.sub(r"<@[A-Z0-9]+>", "", text)
    # Replace <url|label> with label
    text = re.sub(r"<([^|>]+)\|([^>]+)>", r"\2", text)
    # Replace <url> with url
    text = re.sub(r"<([^>]+)>", r"\1", text)
    return text.strip()


def get_bot_user_id(client: WebClient) -> str | None:
    """Get the bot's own user ID to filter out self-messages."""
    try:
        auth = client.auth_test()
        return auth.get("user_id")
    except Exception:
        return None


def extract_slack_files(files: list[dict] | None, client: WebClient | None = None) -> list[dict]:
    """
    Extract image URLs from Slack file attachments.

    If client is provided, attempts to make files publicly accessible via Slack API.
    """
    if not files:
        return []

    images = []
    for f in files:
        mimetype = f.get("mimetype", "")
        if not mimetype.startswith("image/"):
            continue

        file_id = f.get("id")
        url = f.get("permalink_public")

        # If no public URL and we have a client, try to make it public
        if not url and client and file_id:
            try:
                result = client.files_sharedPublicURL(file=file_id)
                if result.get("ok"):
                    # The API returns the file with permalink_public populated
                    url = result.get("file", {}).get("permalink_public")
            except Exception as e:
                logger.debug("slack_file_share_public_failed", file_id=file_id, error=str(e))

        # Fall back to url_private (won't work without auth, but store it anyway)
        if not url:
            url = f.get("url_private")

        if url:
            images.append(
                {
                    "url": url,
                    "name": f.get("name", "image"),
                    "mimetype": mimetype,
                    "thumb": f.get("thumb_360") or f.get("thumb_160"),
                }
            )
    return images


def create_or_update_slack_ticket(
    *,
    team: Team,
    integration: Integration,
    slack_channel_id: str,
    thread_ts: str,
    slack_user_id: str,
    text: str,
    files: list[dict] | None = None,
    is_thread_reply: bool = False,
) -> Ticket | None:
    """
    Core function: create a new ticket or add a message to an existing one.

    For new tickets (is_thread_reply=False):
      - Creates Ticket with channel_source="slack"
      - Creates first Comment

    For thread replies (is_thread_reply=True):
      - Finds existing Ticket by slack_channel_id + slack_thread_ts
      - Creates a new Comment on that ticket
    """
    client = get_slack_client(team, integration)

    # Extract images from Slack files, making them publicly accessible
    images = extract_slack_files(files, client)

    if is_thread_reply:
        ticket = Ticket.objects.filter(
            team=team,
            slack_channel_id=slack_channel_id,
            slack_thread_ts=thread_ts,
        ).first()

        if not ticket:
            logger.debug(
                "slack_support_thread_reply_no_ticket",
                slack_channel_id=slack_channel_id,
                thread_ts=thread_ts,
            )
            return None

        cleaned_text = clean_slack_text(text)
        # Allow messages with only images (no text)
        if not cleaned_text and not images:
            return ticket

        # Resolve Slack user info for this message author
        user_info = resolve_slack_user(client, slack_user_id)

        # Build content with image markdown if present
        content = cleaned_text
        if images:
            image_markdown = "\n".join(f"![{img['name']}]({img['url']})" for img in images)
            content = f"{cleaned_text}\n\n{image_markdown}" if cleaned_text else image_markdown

        Comment.objects.create(
            team=team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=content,
            item_context={
                "author_type": "customer",
                "is_private": False,
                "slack_user_id": slack_user_id,
                "slack_author_name": user_info["name"],
                "slack_author_email": user_info.get("email"),
                "slack_author_avatar": user_info.get("avatar"),
                "slack_images": images if images else None,
            },
        )

        # Increment unread_team_count
        Ticket.objects.filter(id=ticket.id).update(
            unread_team_count=ticket.unread_team_count + 1,
        )

        return ticket

    # New ticket from top-level message
    user_info = resolve_slack_user(client, slack_user_id)
    cleaned_text = clean_slack_text(text)
    # Allow messages with only images (no text)
    if not cleaned_text and not images:
        return None

    # Build content with image markdown if present
    content = cleaned_text
    if images:
        image_markdown = "\n".join(f"![{img['name']}]({img['url']})" for img in images)
        content = f"{cleaned_text}\n\n{image_markdown}" if cleaned_text else image_markdown

    ticket = Ticket.objects.create_with_number(
        team=team,
        channel_source=Channel.SLACK,
        widget_session_id="",  # Not used for Slack tickets
        distinct_id="",  # Will be linked later if email matches a person
        status=Status.NEW,
        anonymous_traits={
            "name": user_info["name"],
            **({"email": user_info["email"]} if user_info["email"] else {}),
        },
        slack_channel_id=slack_channel_id,
        slack_thread_ts=thread_ts,
        unread_team_count=1,
    )

    Comment.objects.create(
        team=team,
        scope="conversations_ticket",
        item_id=str(ticket.id),
        content=content,
        item_context={
            "author_type": "customer",
            "is_private": False,
            "slack_user_id": slack_user_id,
            "slack_author_name": user_info["name"],
            "slack_author_email": user_info.get("email"),
            "slack_author_avatar": user_info.get("avatar"),
            "slack_images": images if images else None,
        },
    )

    # Post a confirmation reply in the Slack thread
    ticket_url = f"{settings.SITE_URL}/project/{team.id}/support/tickets/{ticket.id}"
    try:
        client.chat_postMessage(
            channel=slack_channel_id,
            thread_ts=thread_ts,
            text=f"Ticket #{ticket.ticket_number} created.",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":ticket: Ticket #{ticket.ticket_number} created",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "View in PostHog", "emoji": True},
                            "url": ticket_url,
                        }
                    ],
                },
            ],
        )
    except Exception:
        logger.warning("slack_support_confirmation_failed", ticket_id=str(ticket.id))

    return ticket


def handle_support_message(event: dict, integration: Integration) -> None:
    """
    Handle a Slack 'message' event for the dedicated support channel.

    Top-level messages create new tickets.
    Thread replies add messages to existing tickets.
    """
    channel = event.get("channel")
    if not channel:
        return

    # Skip bot messages to prevent loops
    if event.get("bot_id") or event.get("subtype") in ("bot_message", "message_changed", "message_deleted"):
        return

    slack_user_id = event.get("user")
    text = event.get("text", "")
    files = event.get("files")  # Slack file attachments (images, etc.)

    # Require either text or files
    if not slack_user_id or (not text.strip() and not files):
        return

    team = integration.team
    settings_dict = team.conversations_settings or {}
    configured_channel = settings_dict.get("slack_channel_id")

    if not configured_channel or configured_channel != channel:
        return

    thread_ts = event.get("thread_ts")
    message_ts = event.get("ts")

    if thread_ts:
        # Thread reply -> add message to existing ticket
        create_or_update_slack_ticket(
            team=team,
            integration=integration,
            slack_channel_id=channel,
            thread_ts=thread_ts,
            slack_user_id=slack_user_id,
            text=text,
            files=files,
            is_thread_reply=True,
        )
    else:
        # Top-level message -> create new ticket, use message ts as thread_ts
        create_or_update_slack_ticket(
            team=team,
            integration=integration,
            slack_channel_id=channel,
            thread_ts=message_ts or "",
            slack_user_id=slack_user_id,
            text=text,
            files=files,
            is_thread_reply=False,
        )


def handle_support_mention(event: dict, integration: Integration) -> None:
    """
    Handle a Slack 'app_mention' event to create a support ticket.

    The mention message becomes the first message of the ticket.
    """
    channel = event.get("channel")
    slack_user_id = event.get("user")
    text = event.get("text", "")
    files = event.get("files")
    if not channel or not slack_user_id:
        return

    # Use thread_ts if in a thread, otherwise the message ts
    thread_ts = event.get("thread_ts") or event.get("ts")
    if not thread_ts:
        return

    team = integration.team
    settings_dict = team.conversations_settings or {}

    # Only handle if Slack support is configured
    if not settings_dict.get("slack_integration_id"):
        return

    # Check if a ticket already exists for this thread
    existing = Ticket.objects.filter(
        team=team,
        slack_channel_id=channel,
        slack_thread_ts=thread_ts,
    ).first()

    if existing:
        # Add as a reply to the existing ticket
        create_or_update_slack_ticket(
            team=team,
            integration=integration,
            slack_channel_id=channel,
            thread_ts=thread_ts,
            slack_user_id=slack_user_id,
            text=text,
            files=files,
            is_thread_reply=True,
        )
    else:
        create_or_update_slack_ticket(
            team=team,
            integration=integration,
            slack_channel_id=channel,
            thread_ts=thread_ts,
            slack_user_id=slack_user_id,
            text=text,
            files=files,
            is_thread_reply=False,
        )


def handle_support_reaction(event: dict, integration: Integration) -> None:
    """
    Handle a Slack 'reaction_added' event to create a ticket from a reacted message.

    Fetches the reacted-to message and creates a ticket from it.
    Subsequent thread replies become ticket messages.
    """
    reaction = event.get("reaction", "")
    item = event.get("item", {})
    channel = item.get("channel")
    message_ts = item.get("ts")

    if not channel or not message_ts:
        return

    team = integration.team
    settings_dict = team.conversations_settings or {}
    configured_emoji = settings_dict.get("slack_ticket_emoji", "ticket")

    if reaction != configured_emoji:
        return

    # Only handle if Slack support is configured
    if not settings_dict.get("slack_integration_id"):
        return

    # Check if a ticket already exists for this message thread
    existing = Ticket.objects.filter(
        team=team,
        slack_channel_id=channel,
        slack_thread_ts=message_ts,
    ).first()

    if existing:
        logger.debug("slack_support_reaction_ticket_exists", ticket_id=str(existing.id))
        return

    # Fetch the reacted-to message to get its content and author
    client = get_slack_client(team, integration)
    try:
        result = client.conversations_history(
            channel=channel,
            latest=message_ts,
            inclusive=True,
            limit=1,
        )
        messages = result.get("messages", [])
        if not messages:
            return

        original_msg = messages[0]
        original_user = original_msg.get("user", "")
        original_text = original_msg.get("text", "")
        original_files = original_msg.get("files")
    except Exception:
        logger.warning("slack_support_reaction_fetch_failed", channel=channel, message_ts=message_ts)
        return

    # Require either text or files
    if not original_text.strip() and not original_files:
        return

    create_or_update_slack_ticket(
        team=team,
        integration=integration,
        slack_channel_id=channel,
        thread_ts=message_ts,
        slack_user_id=original_user,
        text=original_text,
        files=original_files,
        is_thread_reply=False,
    )
