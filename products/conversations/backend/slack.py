"""
Slack inbound handler for the support/conversations product.

Handles three triggers that create or update tickets from Slack:
1. Dedicated channels: messages in any configured support channel
2. Bot mention: @mention the bot to create a ticket
3. Emoji reaction: react with a configurable emoji to create a ticket from a message

All three converge to create_or_update_slack_ticket().
"""

from types import MappingProxyType
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.db.models import F

import structlog
from slack_sdk import WebClient

from posthog.models.comment import Comment
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from .cache import get_cached_slack_avatar, get_cached_slack_user, set_cached_slack_avatar, set_cached_slack_user
from .formatting import extract_slack_user_ids, slack_to_content_and_rich_content
from .models import Ticket
from .models.constants import Channel, ChannelDetail, Status
from .services.attachments import is_valid_image, save_file_to_uploaded_media
from .support_slack import (
    SUPPORT_SLACK_ALLOWED_HOST_SUFFIXES,
    SUPPORT_SLACK_MAX_IMAGE_BYTES,
    get_support_slack_bot_token,
)

logger = structlog.get_logger(__name__)
SLACK_DOWNLOAD_TIMEOUT_SECONDS = 10
MAX_REDIRECTS = 5


def _get_team_id(team: Team) -> int:
    team_id = getattr(team, "id", None)
    if not isinstance(team_id, int):
        raise ValueError("Invalid team id")
    return team_id


def _build_content_with_images(
    cleaned_text: str, rich_content: dict[str, Any] | None, images: list[dict[str, Any]]
) -> tuple[str, dict[str, Any] | None]:
    content = cleaned_text
    if not images:
        return content, rich_content

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
    return content, rich_content


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
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


_UNKNOWN_USER = MappingProxyType({"name": "Unknown", "email": None, "avatar": None})


def resolve_slack_user(client: WebClient, slack_user_id: str) -> dict:
    """Resolve a Slack user ID to name, email, and avatar. Cached in Redis for 5 minutes."""
    if not slack_user_id:
        logger.warning("slack_support_user_resolve_empty_id")
        return dict(_UNKNOWN_USER)

    cached = get_cached_slack_user(slack_user_id)
    if cached is not None:
        return cached

    try:
        response = client.users_info(user=slack_user_id)
        raw_data = response.data if hasattr(response, "data") else None
        data: dict = raw_data if isinstance(raw_data, dict) else {}

        if not data.get("ok"):
            logger.warning(
                "slack_support_user_resolve_not_ok",
                slack_user_id=slack_user_id,
                error=data.get("error"),
            )
            return dict(_UNKNOWN_USER)

        user_data = data.get("user") or {}
        profile = user_data.get("profile") or {}
        name = profile.get("display_name") or profile.get("real_name") or "Unknown"
        result = {
            "name": name,
            "email": profile.get("email"),
            "avatar": profile.get("image_72"),
        }
        set_cached_slack_user(slack_user_id, result)
        return result
    except Exception as e:
        logger.warning("slack_support_user_resolve_failed", slack_user_id=slack_user_id, error=str(e))
        return dict(_UNKNOWN_USER)


def resolve_slack_avatar_by_email(client: WebClient, email: str) -> str | None:
    """Look up a Slack user by email and return their profile image URL. Cached in Redis."""
    if not email:
        return None

    cached = get_cached_slack_avatar(email)
    if cached is not None:
        return cached or None  # empty string = negative cache

    try:
        response = client.users_lookupByEmail(email=email)
        raw_data = response.data if hasattr(response, "data") else None
        data: dict = raw_data if isinstance(raw_data, dict) else {}

        if not data.get("ok"):
            set_cached_slack_avatar(email, "")
            return None

        profile = (data.get("user") or {}).get("profile") or {}
        avatar = profile.get("image_72") or ""
        set_cached_slack_avatar(email, avatar)
        return avatar or None
    except Exception:
        # Don't negative-cache on transient errors (rate limits, network)
        # so the next reply retries the lookup.
        logger.warning("slack_avatar_lookup_failed", email=email)
        return None


def resolve_posthog_user_for_slack(email: str | None, team: Team) -> User | None:
    """Match a Slack user's email to a PostHog user within the team's organization."""
    if not email:
        return None
    membership = (
        OrganizationMembership.objects.filter(
            organization_id=team.organization_id,
            user__email=email,
        )
        .select_related("user")
        .first()
    )
    return membership.user if membership else None


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
    return any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in SUPPORT_SLACK_ALLOWED_HOST_SUFFIXES)


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
                    if int(content_length_header) > SUPPORT_SLACK_MAX_IMAGE_BYTES:
                        logger.warning(
                            "🖼️ slack_file_download_too_large_from_header",
                            url=next_url,
                            content_length=int(content_length_header),
                            max_allowed=SUPPORT_SLACK_MAX_IMAGE_BYTES,
                        )
                        return None
                except ValueError:
                    logger.warning(
                        "🖼️ slack_file_download_invalid_content_length", url=next_url, value=content_length_header
                    )
                    return None
            payload = response.read(SUPPORT_SLACK_MAX_IMAGE_BYTES + 1)
            if len(payload) > SUPPORT_SLACK_MAX_IMAGE_BYTES:
                logger.warning(
                    "🖼️ slack_file_download_too_large_from_body",
                    url=next_url,
                    bytes_read=len(payload),
                    max_allowed=SUPPORT_SLACK_MAX_IMAGE_BYTES,
                )
                return None
            logger.debug("🖼️ slack_file_download_succeeded", url=next_url, bytes_read=len(payload))
            return payload

    logger.warning("🖼️ slack_file_download_too_many_redirects", url=url, max_redirects=MAX_REDIRECTS)
    return None


def extract_slack_files(files: list[dict] | None, team: Team, client: WebClient | None = None) -> list[dict]:
    """
    Extract image attachments from Slack and re-host them in UploadedMedia.
    """
    if not files:
        return []

    team_id = _get_team_id(team)
    bot_token = getattr(client, "token", None) if client else None
    logger.info("🖼️ slack_file_extract_started", team_id=team_id, total_files=len(files), has_bot_token=bool(bot_token))
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

        if not is_valid_image(image_bytes):
            logger.warning("🖼️ slack_file_invalid_image_content", file_id=file_id)
            continue

        stored_url = save_file_to_uploaded_media(
            team, f.get("name", "image"), mimetype, image_bytes, validate_images=False
        )
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
    logger.info("🖼️ slack_file_extract_finished", team_id=team_id, image_count=len(images))
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
    channel_detail: ChannelDetail | None = None,
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
    team_id = _get_team_id(team)
    client = get_slack_client(team)
    logger.info(
        "🧵 slack_support_ticket_ingest_started",
        team_id=team_id,
        slack_channel_id=slack_channel_id,
        thread_ts=thread_ts,
        is_thread_reply=is_thread_reply,
        has_text=bool(text and text.strip()),
        files_count=len(files or []),
    )

    # Extract images from Slack files, making them publicly accessible
    images = extract_slack_files(files, team, client)

    # Resolve Slack user info for this message author
    user_info = resolve_slack_user(client, slack_user_id)

    # Check if this Slack user is a PostHog team member
    posthog_user = resolve_posthog_user_for_slack(user_info.get("email"), team)
    is_team_member = posthog_user is not None

    # Resolve in-message @mentions to display names
    mentioned_ids = extract_slack_user_ids(text, blocks)
    user_names: dict[str, str] = {}
    for uid in mentioned_ids:
        if uid == slack_user_id and user_info["name"] != "Unknown":
            user_names[uid] = user_info["name"]
        elif uid not in user_names:
            info = resolve_slack_user(client, uid)
            if info["name"] != "Unknown":
                user_names[uid] = info["name"]

    # Convert Slack payload to markdown content and rich_content
    cleaned_text, rich_content = slack_to_content_and_rich_content(text, blocks, user_names=user_names)

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
            Ticket.objects.filter(id=ticket.id, team=team).update(slack_team_id=slack_team_id)

        # Allow messages with only images (no text)
        if not cleaned_text and not images:
            logger.warning(
                "🧵 slack_support_ticket_ingest_empty_after_processing",
                team_id=team_id,
                slack_channel_id=slack_channel_id,
                thread_ts=thread_ts,
                is_thread_reply=is_thread_reply,
            )
            return ticket

        content, rich_content = _build_content_with_images(cleaned_text, rich_content, images)

        Comment.objects.create(
            team=team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=content,
            rich_content=rich_content,
            created_by=posthog_user,
            item_context={
                "author_type": "support" if is_team_member else "customer",
                "is_private": False,
                "from_slack": True,
                "slack_user_id": slack_user_id,
                "slack_author_name": user_info["name"],
                "slack_author_email": user_info.get("email"),
                "slack_author_avatar": user_info.get("avatar"),
                "slack_images": images if images else None,
            },
        )

        if not is_team_member:
            Ticket.objects.filter(id=ticket.id, team=team).update(
                unread_team_count=F("unread_team_count") + 1,
            )

        return ticket

    # New ticket from top-level message
    # Allow messages with only images (no text)
    if not cleaned_text and not images:
        logger.warning(
            "🧵 slack_support_ticket_ingest_empty_after_processing",
            team_id=team_id,
            slack_channel_id=slack_channel_id,
            thread_ts=thread_ts,
            is_thread_reply=is_thread_reply,
        )
        return None

    content, rich_content = _build_content_with_images(cleaned_text, rich_content, images)

    ticket = Ticket.objects.create_with_number(
        team=team,
        channel_source=Channel.SLACK,
        channel_detail=channel_detail,
        widget_session_id="",  # Not used for Slack tickets
        distinct_id=user_info.get("email") or "",
        status=Status.NEW,
        anonymous_traits={
            "name": user_info["name"],
            **({"email": user_info["email"]} if user_info["email"] else {}),
        },
        slack_channel_id=slack_channel_id,
        slack_thread_ts=thread_ts,
        slack_team_id=slack_team_id,
        unread_team_count=0 if is_team_member else 1,
    )

    Comment.objects.create(
        team=team,
        scope="conversations_ticket",
        item_id=str(ticket.id),
        content=content,
        rich_content=rich_content,
        created_by=posthog_user,
        item_context={
            "author_type": "support" if is_team_member else "customer",
            "is_private": False,
            "from_slack": True,
            "slack_user_id": slack_user_id,
            "slack_author_name": user_info["name"],
            "slack_author_email": user_info.get("email"),
            "slack_author_avatar": user_info.get("avatar"),
            "slack_images": images if images else None,
        },
    )

    # Post a confirmation reply in the Slack thread
    # ticket_url = f"{settings.SITE_URL}/project/{team_id}/support/tickets/{ticket.id}"
    support_settings = team.conversations_settings or {}
    confirmation_kwargs: dict = {
        "channel": slack_channel_id,
        "thread_ts": thread_ts,
        "text": f"Ticket #{ticket.ticket_number} created.",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":ticket: Ticket #{ticket.ticket_number} created",
                },
            },
            # {
            #     "type": "actions",
            #     "elements": [
            #         {
            #             "type": "button",
            #             "text": {"type": "plain_text", "text": "View in PostHog", "emoji": True},
            #             "url": ticket_url,
            #         }
            #     ],
            # },
        ],
    }
    bot_display_name = support_settings.get("slack_bot_display_name")
    bot_icon_url = support_settings.get("slack_bot_icon_url")
    if bot_display_name:
        confirmation_kwargs["username"] = bot_display_name
    if bot_icon_url:
        confirmation_kwargs["icon_url"] = bot_icon_url
    try:
        client.chat_postMessage(**confirmation_kwargs)
    except Exception:
        logger.warning("slack_support_confirmation_failed", ticket_id=str(ticket.id))

    return ticket


def _configured_support_channels(settings: dict) -> set[str]:
    """Return the set of Slack channel IDs configured for auto-ticket creation.

    Merges the new ``slack_channel_ids`` list with the legacy scalar
    ``slack_channel_id`` so that teams that haven't re-saved settings after
    the multi-channel migration still work.
    """
    ids = set(settings.get("slack_channel_ids") or [])
    legacy = settings.get("slack_channel_id")
    if legacy:
        ids.add(legacy)
    return ids


def handle_support_message(event: dict, team: Team, slack_team_id: str) -> None:
    """
    Handle a Slack 'message' event for configured support channels.

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
    configured_channels = _configured_support_channels(settings_dict)
    thread_ts = event.get("thread_ts")
    message_ts = event.get("ts")

    if thread_ts:
        # Thread replies should sync even outside a configured channel when a
        # ticket already exists for that thread (e.g. ticket created via @mention).
        if not Ticket.objects.filter(team=team, slack_channel_id=channel, slack_thread_ts=thread_ts).exists():
            if channel not in configured_channels:
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

    if channel not in configured_channels:
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
        channel_detail=ChannelDetail.SLACK_CHANNEL_MESSAGE,
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
    ).exists()

    create_or_update_slack_ticket(
        team=team,
        slack_channel_id=channel,
        thread_ts=thread_ts,
        slack_user_id=slack_user_id,
        text=text,
        blocks=blocks,
        files=files,
        is_thread_reply=existing,
        slack_team_id=slack_team_id,
        channel_detail=ChannelDetail.SLACK_BOT_MENTION,
    )


def _backfill_thread_replies(
    client: WebClient,
    team: Team,
    ticket: Ticket,
    channel: str,
    thread_ts: str,
) -> None:
    """Fetch existing thread replies and add them as comments on the ticket."""
    try:
        result = client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
        replies: list[dict] = result.get("messages", [])
    except Exception:
        logger.warning("slack_support_reaction_backfill_failed", channel=channel, thread_ts=thread_ts)
        return

    thread_replies = [r for r in replies if r.get("ts") != thread_ts]
    if not thread_replies:
        return

    logger.info(
        "slack_support_reaction_backfill_started",
        channel=channel,
        thread_ts=thread_ts,
        ticket_id=str(ticket.id),
        thread_reply_count=len(thread_replies),
    )

    user_cache: dict[str, dict] = {}
    posthog_user_cache: dict[str, User | None] = {}
    comments_to_create: list[Comment] = []
    customer_message_count = 0
    team_message_count = 0

    for reply in thread_replies:
        # Match the bot/subtype filtering from handle_support_message
        if reply.get("bot_id") or reply.get("subtype") in ("bot_message", "message_changed", "message_deleted"):
            continue

        reply_user = reply.get("user", "")
        reply_text = reply.get("text", "")
        reply_blocks = reply.get("blocks")
        reply_files = reply.get("files")

        if not reply_text.strip() and not reply_files:
            continue

        images = extract_slack_files(reply_files, team, client)

        if reply_user not in user_cache:
            user_cache[reply_user] = resolve_slack_user(client, reply_user)
        user_info = user_cache[reply_user]

        if reply_user not in posthog_user_cache:
            posthog_user_cache[reply_user] = resolve_posthog_user_for_slack(user_info.get("email"), team)
        posthog_user = posthog_user_cache[reply_user]
        is_team_member = posthog_user is not None

        # Resolve in-message @mentions to display names
        mentioned_ids = extract_slack_user_ids(reply_text, reply_blocks)
        reply_user_names: dict[str, str] = {}
        for uid in mentioned_ids:
            if uid not in user_cache:
                user_cache[uid] = resolve_slack_user(client, uid)
            if user_cache[uid]["name"] != "Unknown":
                reply_user_names[uid] = user_cache[uid]["name"]

        cleaned_text, rich_content = slack_to_content_and_rich_content(
            reply_text, reply_blocks, user_names=reply_user_names
        )
        if not cleaned_text and not images:
            continue

        if is_team_member:
            team_message_count += 1
        else:
            customer_message_count += 1

        content, rich_content = _build_content_with_images(cleaned_text, rich_content, images)

        comments_to_create.append(
            Comment(
                team=team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content=content,
                rich_content=rich_content,
                created_by=posthog_user,
                item_context={
                    "author_type": "support" if is_team_member else "customer",
                    "is_private": False,
                    "from_slack": True,
                    "slack_user_id": reply_user,
                    "slack_author_name": user_info["name"],
                    "slack_author_email": user_info.get("email"),
                    "slack_author_avatar": user_info.get("avatar"),
                    "slack_images": images if images else None,
                },
            )
        )

    if comments_to_create:
        # bulk_create intentionally skips post_save signals — backfilled historical
        # messages should not trigger activity log entries or Slack reply notifications.
        created_comments = Comment.objects.bulk_create(comments_to_create)
        last_comment = created_comments[-1]
        update_fields: dict[str, Any] = {
            "message_count": F("message_count") + len(comments_to_create),
            "last_message_at": last_comment.created_at,
            "last_message_text": (last_comment.content or "")[:500],
        }
        if customer_message_count:
            update_fields["unread_team_count"] = F("unread_team_count") + customer_message_count
        if team_message_count:
            update_fields["unread_customer_count"] = F("unread_customer_count") + team_message_count
        Ticket.objects.filter(id=ticket.id, team=team).update(**update_fields)

    logger.info(
        "slack_support_reaction_backfill_completed",
        channel=channel,
        thread_ts=thread_ts,
        ticket_id=str(ticket.id),
        backfilled_count=len(comments_to_create),
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
        messages: list[dict] = result.get("messages", [])
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

    ticket = create_or_update_slack_ticket(
        team=team,
        slack_channel_id=channel,
        thread_ts=message_ts,
        slack_user_id=original_user,
        text=original_text,
        blocks=original_blocks,
        files=original_files,
        is_thread_reply=False,
        slack_team_id=slack_team_id,
        channel_detail=ChannelDetail.SLACK_EMOJI_REACTION,
    )

    if ticket:
        _backfill_thread_replies(client, team, ticket, channel, message_ts)
