"""
Slack inbound handler for the support/conversations product.

Handles three triggers that create or update tickets from Slack:
1. Dedicated channel: messages in a configured support channel
2. Bot mention: @mention the bot to create a ticket
3. Emoji reaction: react with a configurable emoji to create a ticket from a message

All three converge to create_or_update_slack_ticket().
"""

from io import BytesIO
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings
from django.db.models import F

import structlog
from PIL import Image
from slack_sdk import WebClient

from posthog.models.comment import Comment
from posthog.models.team.team import Team
from posthog.models.uploaded_media import UploadedMedia, save_content_to_object_storage

from .formatting import slack_to_content_and_rich_content
from .models import Ticket
from .models.constants import Channel, Status
from .support_slack import get_support_slack_bot_token

logger = structlog.get_logger(__name__)
MAX_IMAGE_BYTES = 4 * 1024 * 1024
SLACK_DOWNLOAD_TIMEOUT_SECONDS = 10
ALLOWED_SLACK_FILE_HOST_SUFFIXES = ("slack.com", "slack-edge.com", "slack-files.com")
MAX_REDIRECTS = 5


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def get_slack_client(team: Team) -> WebClient:
    """
    Get a Slack WebClient for the team.

    Uses the team-scoped SupportHog bot token when configured.
    """
    bot_token = get_support_slack_bot_token(team)
    if bot_token:
        return WebClient(token=bot_token)
    raise ValueError("Support Slack bot token is not configured")


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


def get_bot_user_id(client: WebClient) -> str | None:
    """Get the bot's own user ID to filter out self-messages."""
    try:
        auth = client.auth_test()
        return auth.get("user_id")
    except Exception:
        return None


def _is_allowed_slack_file_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if parsed.scheme != "https":
        return False
    return any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in ALLOWED_SLACK_FILE_HOST_SUFFIXES)


def _is_valid_image_bytes(content: bytes) -> bool:
    try:
        image = Image.open(BytesIO(content))
        image.transpose(Image.FLIP_LEFT_RIGHT)
        image.close()
        return True
    except Exception:
        return False


def _download_slack_image_bytes(url: str, bot_token: str) -> bytes | None:
    if not _is_allowed_slack_file_url(url):
        logger.warning("🖼️ slack_file_download_invalid_host", url=url)
        return None

    opener = build_opener(_NoRedirectHandler)
    next_url = url

    for _ in range(MAX_REDIRECTS + 1):
        request = Request(next_url, headers={"Authorization": f"Bearer {bot_token}"})
        with opener.open(request, timeout=SLACK_DOWNLOAD_TIMEOUT_SECONDS) as response:
            status = response.getcode()
            if status in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    logger.warning("🖼️ slack_file_download_redirect_missing_location", url=next_url, status=status)
                    return None
                redirect_url = urljoin(next_url, location)
                if not _is_allowed_slack_file_url(redirect_url):
                    logger.warning("🖼️ slack_file_download_invalid_redirect_host", url=redirect_url)
                    return None
                next_url = redirect_url
                logger.debug("🖼️ slack_file_download_redirect", status=status, redirect_url=redirect_url)
                continue

            if status != 200:
                logger.warning("🖼️ slack_file_download_non_200", url=next_url, status=status)
                return None

            content_length_header = response.headers.get("Content-Length")
            if content_length_header:
                try:
                    if int(content_length_header) > MAX_IMAGE_BYTES:
                        logger.warning(
                            "🖼️ slack_file_download_too_large_from_header",
                            url=next_url,
                            content_length=int(content_length_header),
                            max_allowed=MAX_IMAGE_BYTES,
                        )
                        return None
                except ValueError:
                    logger.warning(
                        "🖼️ slack_file_download_invalid_content_length", url=next_url, value=content_length_header
                    )
                    return None
            payload = response.read(MAX_IMAGE_BYTES + 1)
            if len(payload) > MAX_IMAGE_BYTES:
                logger.warning(
                    "🖼️ slack_file_download_too_large_from_body",
                    url=next_url,
                    bytes_read=len(payload),
                    max_allowed=MAX_IMAGE_BYTES,
                )
                return None
            logger.debug("🖼️ slack_file_download_succeeded", url=next_url, bytes_read=len(payload))
            return payload

    logger.warning("🖼️ slack_file_download_too_many_redirects", url=url, max_redirects=MAX_REDIRECTS)
    return None


def _save_image_to_uploaded_media(team: Team, file_name: str, mimetype: str, content: bytes) -> str | None:
    if not settings.OBJECT_STORAGE_ENABLED:
        logger.warning("🖼️ slack_file_copy_no_object_storage", team_id=team.id)
        return None

    uploaded_media = UploadedMedia.objects.create(
        team=team,
        file_name=file_name,
        content_type=mimetype,
        created_by=None,
    )
    try:
        save_content_to_object_storage(uploaded_media, content)
    except Exception as e:
        logger.warning("🖼️ slack_file_copy_storage_failed", uploaded_media_id=str(uploaded_media.id), error=str(e))
        uploaded_media.delete()
        return None
    logger.info(
        "🖼️ slack_file_copy_saved",
        team_id=team.id,
        uploaded_media_id=str(uploaded_media.id),
        file_name=file_name,
        content_type=mimetype,
        bytes_size=len(content),
    )
    return uploaded_media.get_absolute_url()


def extract_slack_files(files: list[dict] | None, team: Team, client: WebClient | None = None) -> list[dict]:
    """
    Extract image attachments from Slack and re-host them in UploadedMedia.
    """
    if not files:
        return []

    bot_token = getattr(client, "token", None) if client else None
    logger.info("🖼️ slack_file_extract_started", team_id=team.id, total_files=len(files), has_bot_token=bool(bot_token))
    images = []
    for f in files:
        mimetype = f.get("mimetype", "")
        if not mimetype.startswith("image/"):
            logger.debug("🖼️ slack_file_extract_skipped_non_image", file_id=f.get("id"), mimetype=mimetype)
            continue

        file_id = f.get("id")
        source_url = f.get("url_private_download") or f.get("url_private")
        if not source_url or not bot_token:
            logger.warning(
                "🖼️ slack_file_missing_download_info",
                file_id=file_id,
                has_source_url=bool(source_url),
                has_bot_token=bool(bot_token),
            )
            continue

        try:
            image_bytes = _download_slack_image_bytes(source_url, bot_token)
        except Exception as e:
            logger.warning("🖼️ slack_file_download_failed", file_id=file_id, error=str(e))
            continue

        if not image_bytes:
            logger.warning("🖼️ slack_file_download_rejected", file_id=file_id, source_url=source_url)
            continue

        if not _is_valid_image_bytes(image_bytes):
            logger.warning("🖼️ slack_file_invalid_image_content", file_id=file_id)
            continue

        stored_url = _save_image_to_uploaded_media(team, f.get("name", "image"), mimetype, image_bytes)
        if stored_url:
            images.append(
                {
                    "url": stored_url,
                    "name": f.get("name", "image"),
                    "mimetype": mimetype,
                    "thumb": f.get("thumb_360") or f.get("thumb_160"),
                }
            )
        else:
            logger.warning("🖼️ slack_file_copy_save_failed", file_id=file_id)
    logger.info("🖼️ slack_file_extract_finished", team_id=team.id, image_count=len(images))
    return images


def create_or_update_slack_ticket(
    *,
    team: Team,
    slack_channel_id: str,
    thread_ts: str,
    slack_user_id: str,
    text: str,
    blocks: list[dict] | None = None,
    files: list[dict] | None = None,
    is_thread_reply: bool = False,
    slack_team_id: str | None = None,
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
    client = get_slack_client(team)
    logger.info(
        "🧵 slack_support_ticket_ingest_started",
        team_id=team.id,
        slack_channel_id=slack_channel_id,
        thread_ts=thread_ts,
        is_thread_reply=is_thread_reply,
        has_text=bool(text and text.strip()),
        files_count=len(files or []),
    )

    # Extract images from Slack files, making them publicly accessible
    images = extract_slack_files(files, team, client)

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
        if slack_team_id and not ticket.slack_team_id:
            Ticket.objects.filter(id=ticket.id).update(slack_team_id=slack_team_id)

        cleaned_text, rich_content = slack_to_content_and_rich_content(text, blocks)
        # Allow messages with only images (no text)
        if not cleaned_text and not images:
            logger.warning(
                "🧵 slack_support_ticket_ingest_empty_after_processing",
                team_id=team.id,
                slack_channel_id=slack_channel_id,
                thread_ts=thread_ts,
                is_thread_reply=is_thread_reply,
            )
            return ticket

        # Resolve Slack user info for this message author
        user_info = resolve_slack_user(client, slack_user_id)

        # Build content with image markdown if present
        content = cleaned_text
        if images:
            image_markdown = "\n".join(f"![{img['name']}]({img['url']})" for img in images)
            content = f"{cleaned_text}\n\n{image_markdown}" if cleaned_text else image_markdown
            if not isinstance(rich_content, dict):
                rich_content = {"type": "doc", "content": []}
            rich_nodes = rich_content.setdefault("content", [])
            for img in images:
                rich_nodes.append(
                    {
                        "type": "image",
                        "attrs": {"src": img["url"], "alt": img.get("name", "image")},
                    }
                )

        Comment.objects.create(
            team=team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=content,
            rich_content=rich_content,
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
            unread_team_count=F("unread_team_count") + 1,
        )

        return ticket

    # New ticket from top-level message
    user_info = resolve_slack_user(client, slack_user_id)
    cleaned_text, rich_content = slack_to_content_and_rich_content(text, blocks)
    # Allow messages with only images (no text)
    if not cleaned_text and not images:
        logger.warning(
            "🧵 slack_support_ticket_ingest_empty_after_processing",
            team_id=team.id,
            slack_channel_id=slack_channel_id,
            thread_ts=thread_ts,
            is_thread_reply=is_thread_reply,
        )
        return None

    # Build content with image markdown if present
    content = cleaned_text
    if images:
        image_markdown = "\n".join(f"![{img['name']}]({img['url']})" for img in images)
        content = f"{cleaned_text}\n\n{image_markdown}" if cleaned_text else image_markdown
        if not isinstance(rich_content, dict):
            rich_content = {"type": "doc", "content": []}
        rich_nodes = rich_content.setdefault("content", [])
        for img in images:
            rich_nodes.append(
                {
                    "type": "image",
                    "attrs": {"src": img["url"], "alt": img.get("name", "image")},
                }
            )

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
        slack_team_id=slack_team_id,
        unread_team_count=1,
    )

    Comment.objects.create(
        team=team,
        scope="conversations_ticket",
        item_id=str(ticket.id),
        content=content,
        rich_content=rich_content,
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


def handle_support_message(event: dict, team: Team, slack_team_id: str) -> None:
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
    blocks = event.get("blocks")
    files = event.get("files")  # Slack file attachments (images, etc.)

    # Require either text or files
    if not slack_user_id or (not text.strip() and not files):
        return

    settings_dict = team.conversations_settings or {}
    configured_channel = settings_dict.get("slack_channel_id")
    thread_ts = event.get("thread_ts")
    message_ts = event.get("ts")

    if thread_ts:
        # Thread replies should sync even outside the dedicated channel when a ticket
        # already exists for that thread (e.g. ticket created via @mention flow).
        if not Ticket.objects.filter(team=team, slack_channel_id=channel, slack_thread_ts=thread_ts).exists():
            if not configured_channel or configured_channel != channel:
                return

        # Thread reply -> add message to existing ticket
        create_or_update_slack_ticket(
            team=team,
            slack_channel_id=channel,
            thread_ts=thread_ts,
            slack_user_id=slack_user_id,
            text=text,
            blocks=blocks,
            files=files,
            is_thread_reply=True,
            slack_team_id=slack_team_id,
        )
        return

    if not configured_channel or configured_channel != channel:
        return

    # Top-level message -> create new ticket, use message ts as thread_ts
    create_or_update_slack_ticket(
        team=team,
        slack_channel_id=channel,
        thread_ts=message_ts or "",
        slack_user_id=slack_user_id,
        text=text,
        blocks=blocks,
        files=files,
        is_thread_reply=False,
        slack_team_id=slack_team_id,
    )


def handle_support_mention(event: dict, team: Team, slack_team_id: str) -> None:
    """
    Handle a Slack 'app_mention' event to create a support ticket.

    The mention message becomes the first message of the ticket.
    """
    channel = event.get("channel")
    slack_user_id = event.get("user")
    text = event.get("text", "")
    blocks = event.get("blocks")
    files = event.get("files")
    if not channel or not slack_user_id:
        return

    # Use thread_ts if in a thread, otherwise the message ts
    thread_ts = event.get("thread_ts") or event.get("ts")
    if not thread_ts:
        return

    settings_dict = team.conversations_settings or {}

    # Only handle if Slack support is configured
    if not settings_dict.get("slack_enabled"):
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
            slack_channel_id=channel,
            thread_ts=thread_ts,
            slack_user_id=slack_user_id,
            text=text,
            blocks=blocks,
            files=files,
            is_thread_reply=True,
            slack_team_id=slack_team_id,
        )
    else:
        create_or_update_slack_ticket(
            team=team,
            slack_channel_id=channel,
            thread_ts=thread_ts,
            slack_user_id=slack_user_id,
            text=text,
            blocks=blocks,
            files=files,
            is_thread_reply=False,
            slack_team_id=slack_team_id,
        )


def handle_support_reaction(event: dict, team: Team, slack_team_id: str) -> None:
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

    settings_dict = team.conversations_settings or {}
    configured_emoji = settings_dict.get("slack_ticket_emoji", "ticket")

    if reaction != configured_emoji:
        return

    # Only handle if Slack support is configured
    if not settings_dict.get("slack_enabled"):
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
    client = get_slack_client(team)
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
        original_blocks = original_msg.get("blocks")
        original_files = original_msg.get("files")
    except Exception:
        logger.warning("slack_support_reaction_fetch_failed", channel=channel, message_ts=message_ts)
        return

    # Require either text or files
    if not original_text.strip() and not original_files:
        return

    create_or_update_slack_ticket(
        team=team,
        slack_channel_id=channel,
        thread_ts=message_ts,
        slack_user_id=original_user,
        text=original_text,
        blocks=original_blocks,
        files=original_files,
        is_thread_reply=False,
        slack_team_id=slack_team_id,
    )
