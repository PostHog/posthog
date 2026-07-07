"""
Slack inbound handler for the support/conversations product.

Handles three triggers that create or update tickets from Slack:
1. Dedicated channels: messages in any configured support channel
2. Bot mention: @mention the bot to create a ticket
3. Emoji reaction: react with a configurable emoji to create a ticket from a message

All three converge to create_or_update_slack_ticket().
"""

import re
from types import MappingProxyType
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.db.models import F

import structlog
from slack_sdk import WebClient

from posthog.event_usage import report_team_action
from posthog.models.comment import Comment
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from .cache import (
    get_cached_bot_user_id,
    get_cached_slack_avatar,
    get_cached_slack_user,
    set_cached_bot_user_id,
    set_cached_slack_avatar,
    set_cached_slack_user,
    slack_ticket_create_lock,
)
from .formatting import extract_slack_user_ids, slack_to_content_and_rich_content, strip_slack_user_mentions
from .models import Ticket
from .models.constants import Channel, ChannelDetail, Status
from .services.attachments import (
    CONVERSATIONS_MAX_IMAGE_BYTES,
    build_content_with_images,
    is_valid_image,
    save_file_to_uploaded_media,
)
from .support_slack import SUPPORT_SLACK_ALLOWED_HOST_SUFFIXES, get_support_slack_bot_token

logger = structlog.get_logger(__name__)
SLACK_DOWNLOAD_TIMEOUT_SECONDS = 10
MAX_REDIRECTS = 5

# Slack ID shapes — guard against malformed payloads before interpolating into mrkdwn.
# Permissive on charset (underscores allowed) but blocks angle brackets, @, #, and spaces.
_SLACK_USER_ID_RE = re.compile(r"^[UW][A-Z0-9_]+$")
_SLACK_CHANNEL_ID_RE = re.compile(r"^[CGD][A-Z0-9_]+$")


def _get_team_id(team: Team) -> int:
    team_id = getattr(team, "id", None)
    if not isinstance(team_id, int):
        raise ValueError("Invalid team id")
    return team_id


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


def get_bot_user_id_cached(team: Team, client: WebClient) -> str | None:
    """Resolve the bot's own user ID, cached per team.

    auth.test is Tier-1 rate-limited, so we cache the (stable) result to avoid a
    round-trip per event. Only positive results are cached, so a transient
    auth.test failure retries on the next event rather than being pinned for an hour.
    """
    team_id = _get_team_id(team)
    cached = get_cached_bot_user_id(team_id)
    if cached:
        return cached
    user_id = get_bot_user_id(client)
    if user_id:
        set_cached_bot_user_id(team_id, user_id)
    return user_id


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
                    if int(content_length_header) > CONVERSATIONS_MAX_IMAGE_BYTES:
                        logger.warning(
                            "🖼️ slack_file_download_too_large_from_header",
                            url=next_url,
                            content_length=int(content_length_header),
                            max_allowed=CONVERSATIONS_MAX_IMAGE_BYTES,
                        )
                        return None
                except ValueError:
                    logger.warning(
                        "🖼️ slack_file_download_invalid_content_length", url=next_url, value=content_length_header
                    )
                    return None
            payload = response.read(CONVERSATIONS_MAX_IMAGE_BYTES + 1)
            if len(payload) > CONVERSATIONS_MAX_IMAGE_BYTES:
                logger.warning(
                    "🖼️ slack_file_download_too_large_from_body",
                    url=next_url,
                    bytes_read=len(payload),
                    max_allowed=CONVERSATIONS_MAX_IMAGE_BYTES,
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

        content, rich_content = build_content_with_images(cleaned_text, rich_content, images)

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

    content, rich_content = build_content_with_images(cleaned_text, rich_content, images)

    # Serialize concurrent ticket creation for the same Slack thread via Redis lock.
    # Without this, two reaction_added events from different users race through the
    # .exists() checks above and both create a ticket.
    with slack_ticket_create_lock(team_id, slack_channel_id, thread_ts) as acquired:
        # Return None (not the existing ticket) on every dedup path: the winning worker
        # owns the create-side effects (first comment, confirmation message, and the
        # caller's _backfill_thread_replies). Handing a non-None ticket back to a losing
        # reaction/mention would re-trigger backfill and duplicate every thread comment.
        if not acquired:
            logger.info(
                "slack_ticket_create_lock_not_acquired",
                team_id=team_id,
                slack_channel_id=slack_channel_id,
                thread_ts=thread_ts,
            )
            return None

        # Re-check after acquiring — the winner may have committed between our earlier
        # .exists() call and now.
        if Ticket.objects.filter(team=team, slack_channel_id=slack_channel_id, slack_thread_ts=thread_ts).exists():
            return None

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
            # Created from a signature-validated Slack webhook — platform-attested identity.
            identity_verified=True,
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

    # Always skip non-message subtypes
    if event.get("subtype") in ("message_changed", "message_deleted"):
        return

    is_bot = bool(event.get("bot_id") or event.get("subtype") == "bot_message")

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
        if is_bot:
            # Allow other bots' thread replies but skip our own bot to prevent loops
            try:
                client = get_slack_client(team)
                own_bot_user_id = get_bot_user_id(client)
            except Exception:
                own_bot_user_id = None
            if own_bot_user_id and slack_user_id == own_bot_user_id:
                return

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

    # Top-level bot messages don't create tickets
    if is_bot:
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

    For a top-level mention, the mention message becomes the ticket's first message.
    For a mention posted as a thread reply on an untracked thread, the ticket is
    seeded from the message that started the thread (not the mention itself), then
    the in-between replies are backfilled.
    """
    channel = event.get("channel")
    slack_user_id = event.get("user")
    text = event.get("text", "")
    blocks = event.get("blocks")
    files = event.get("files")
    if not channel or not slack_user_id:
        return

    message_ts = event.get("ts")
    event_thread_ts = event.get("thread_ts")
    # Use thread_ts if in a thread, otherwise the message ts
    thread_ts = event_thread_ts or message_ts
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

    # When the mention is a reply on an untracked thread, the message that started
    # the thread — not the @mention reply — should seed the ticket. Fetch the parent
    # message and create the ticket from it, then backfill the in-between replies
    # (including the mention itself).
    is_thread_reply_mention = bool(event_thread_ts) and event_thread_ts != message_ts
    if not existing and is_thread_reply_mention:
        client = get_slack_client(team)
        try:
            result = client.conversations_history(
                channel=channel,
                latest=thread_ts,
                inclusive=True,
                limit=1,
            )
            messages: list[dict] = result.get("messages", [])
        except Exception:
            logger.warning("slack_support_mention_parent_fetch_failed", channel=channel, thread_ts=thread_ts)
            messages = []

        if messages:
            parent_msg = messages[0]
            parent_user = parent_msg.get("user", "")
            parent_text = parent_msg.get("text", "")
            parent_blocks = parent_msg.get("blocks")
            parent_files = parent_msg.get("files")

            if parent_user and (parent_text.strip() or parent_files):
                ticket = create_or_update_slack_ticket(
                    team=team,
                    slack_channel_id=channel,
                    thread_ts=thread_ts,
                    slack_user_id=parent_user,
                    text=parent_text,
                    blocks=parent_blocks,
                    files=parent_files,
                    is_thread_reply=False,
                    slack_team_id=slack_team_id,
                    channel_detail=ChannelDetail.SLACK_BOT_MENTION,
                )
                if ticket:
                    _backfill_thread_replies(client, team, ticket, channel, thread_ts)
                return

    # A bare "@supporthog" (mention only, no message or files) must not create an empty
    # ticket. The parent-seeding branch above already handled thread-escalation mentions.
    if not strip_slack_user_mentions(text).strip() and not files:
        logger.info(
            "slack_support_mention_empty_skipped",
            team_id=_get_team_id(team),
            slack_channel_id=channel,
            thread_ts=thread_ts,
        )
        return

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
    after_ts: str | None = None,
) -> None:
    """Fetch existing thread replies and add them as comments on the ticket.

    When ``after_ts`` is given, only replies strictly newer than it are backfilled — used
    when a ticket is seeded from a mid-thread message (emoji reaction) so earlier history
    isn't pulled in. Slack ts values are lexicographically ordered, so string comparison is
    safe.
    """
    try:
        result = client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
        replies: list[dict] = result.get("messages", [])
    except Exception:
        logger.warning("slack_support_reaction_backfill_failed", channel=channel, thread_ts=thread_ts)
        return

    thread_replies = [
        r for r in replies if r.get("ts") != thread_ts and (after_ts is None or (r.get("ts") or "") > after_ts)
    ]
    if not thread_replies:
        return

    logger.info(
        "slack_support_reaction_backfill_started",
        channel=channel,
        thread_ts=thread_ts,
        ticket_id=str(ticket.id),
        thread_reply_count=len(thread_replies),
    )

    own_bot_user_id = get_bot_user_id(client)
    user_cache: dict[str, dict] = {}
    posthog_user_cache: dict[str, User | None] = {}
    comments_to_create: list[Comment] = []
    customer_message_count = 0
    team_message_count = 0

    for reply in thread_replies:
        if reply.get("subtype") in ("message_changed", "message_deleted"):
            continue

        # Skip our own bot's messages to prevent loops, but allow other bots
        reply_user = reply.get("user", "")
        if own_bot_user_id and reply_user == own_bot_user_id:
            continue

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

        content, rich_content = build_content_with_images(cleaned_text, rich_content, images)

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

    Unlike a bot mention (which seeds the ticket from the thread root), an emoji reaction
    seeds the ticket from the *reacted* message — "create the ticket from here". If that
    message lives inside a thread, the ticket is still keyed on the thread root so later
    replies route to it, and only replies posted after the reacted message are backfilled.
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

    # Fast path: a ticket may already be anchored on the reacted message ts itself.
    if Ticket.objects.filter(team=team, slack_channel_id=channel, slack_thread_ts=message_ts).exists():
        logger.debug("slack_support_reaction_ticket_exists", channel=channel, thread_ts=message_ts)
        return

    client = get_slack_client(team)

    # Fetch the reacted message together with its thread. conversations.replies returns the
    # whole thread (root first) whether the reaction landed on the root or on a reply.
    # conversations.history only sees top-level channel messages, so reacting on a reply
    # would silently fetch the wrong neighbouring message instead.
    try:
        result = client.conversations_replies(channel=channel, ts=message_ts, limit=200)
        thread_messages: list[dict] = result.get("messages", [])
    except Exception:
        logger.warning("slack_support_reaction_fetch_failed", channel=channel, message_ts=message_ts)
        return

    # A standalone message with no thread can come back empty from conversations.replies —
    # fetch just that message, bounded to its exact ts so we never grab a neighbour.
    if not thread_messages:
        try:
            history = client.conversations_history(
                channel=channel,
                latest=message_ts,
                oldest=message_ts,
                inclusive=True,
                limit=1,
            )
            thread_messages = history.get("messages", [])
        except Exception:
            logger.warning("slack_support_reaction_fetch_failed", channel=channel, message_ts=message_ts)
            return

    if not thread_messages:
        return

    # The reacted message itself seeds the ticket ("create from here").
    reacted_msg = next((m for m in thread_messages if m.get("ts") == message_ts), None)
    if reacted_msg is None:
        # Reacted message wasn't in the fetched window (e.g. a thread with >200 replies that
        # paginated it out). Seed from the thread root instead of silently picking the wrong one.
        logger.warning(
            "slack_support_reaction_message_not_found",
            channel=channel,
            message_ts=message_ts,
            fetched_count=len(thread_messages),
        )
        reacted_msg = thread_messages[0]
    # Slack stamps every threaded message with thread_ts = the true thread root, so derive the
    # root from the reacted message rather than assuming conversations.replies returns it first.
    root_ts = reacted_msg.get("thread_ts") or reacted_msg.get("ts") or message_ts

    # When the reaction lands on a reply, the ticket key (the root) differs from message_ts —
    # re-check so we don't create a duplicate for an already-tracked thread.
    if (
        root_ts != message_ts
        and Ticket.objects.filter(team=team, slack_channel_id=channel, slack_thread_ts=root_ts).exists()
    ):
        logger.debug("slack_support_reaction_ticket_exists", channel=channel, thread_ts=root_ts)
        return

    reacted_text = reacted_msg.get("text", "")
    reacted_files = reacted_msg.get("files")

    # Require either text or files
    if not reacted_text.strip() and not reacted_files:
        return

    ticket = create_or_update_slack_ticket(
        team=team,
        slack_channel_id=channel,
        thread_ts=root_ts,
        slack_user_id=reacted_msg.get("user", ""),
        text=reacted_text,
        blocks=reacted_msg.get("blocks"),
        files=reacted_files,
        is_thread_reply=False,
        slack_team_id=slack_team_id,
        channel_detail=ChannelDetail.SLACK_EMOJI_REACTION,
    )

    if ticket:
        # Only backfill replies posted after the reacted message; earlier thread history is
        # intentionally excluded since the ticket starts from the reacted message.
        _backfill_thread_replies(client, team, ticket, channel, root_ts, after_ts=message_ts)


def _track_bot_joined_channel(event: dict, team: Team, slack_team_id: str, *, own_bot_user_id: str | None) -> None:
    """Fire an internal PostHog event when our own bot is added to a channel.

    Unlike the human join/leave alerts, this isn't gated on any team setting — it's usage
    analytics for PostHog, not a customer-facing Slack message. Only the bot's own join is
    tracked; every other user's join is ignored here.

    There's deliberately no matching "bot left channel" event: Slack delivers
    ``member_left_channel`` only to remaining channel members, so the bot doesn't reliably
    receive its own removal.
    """
    user = event.get("user")
    channel = event.get("channel")
    if not user or not channel:
        return
    if not _SLACK_USER_ID_RE.match(user) or not _SLACK_CHANNEL_ID_RE.match(channel):
        return
    if not own_bot_user_id or user != own_bot_user_id:
        return

    settings_dict = team.conversations_settings or {}
    report_team_action(
        team,
        "support slack bot joined channel",
        {
            "slack_team_id": slack_team_id,
            "slack_channel_id": channel,
            "is_configured_channel": channel in _configured_support_channels(settings_dict),
        },
    )


def _handle_member_event(
    event: dict,
    team: Team,
    *,
    joined: bool,
    client: WebClient | None = None,
    own_bot_user_id: str | None = None,
) -> None:
    """Post a join/leave alert to the configured alert channel.

    Fires for any channel the bot is in (Slack only delivers member_joined_channel /
    member_left_channel for channels the bot belongs to). Gated per-direction by the
    team's settings. Members of the team's own organization are skipped — the alert is
    meant to surface external participants, not internal teammates.

    ``client``/``own_bot_user_id`` may be supplied by the caller so the join path resolves
    the bot identity once for both tracking and alerting; when omitted (leave path) they're
    resolved lazily here, after the gates, so a leave with alerts off does no Slack API work.
    """
    settings_dict = team.conversations_settings or {}

    toggle_key = "slack_notify_on_join" if joined else "slack_notify_on_leave"
    if not settings_dict.get(toggle_key):
        return

    alert_channel = settings_dict.get("slack_alert_channel_id")
    if not isinstance(alert_channel, str) or not alert_channel:
        return

    user = event.get("user")
    channel = event.get("channel")
    if not user or not channel:
        return
    if not _SLACK_USER_ID_RE.match(user) or not _SLACK_CHANNEL_ID_RE.match(channel):
        logger.warning("slack_member_event_malformed_ids", user=user, channel=channel)
        return

    if client is None:
        client = get_slack_client(team)
        own_bot_user_id = get_bot_user_id_cached(team, client)

    # If we can't resolve the bot's own ID (auth.test failed), bail — without it we can't tell
    # the bot's own join apart from a real user's, and posting a self-referential alert is worse
    # than skipping one alert during a transient auth outage.
    if not own_bot_user_id:
        logger.warning("slack_member_event_bot_id_unresolved", team_id=_get_team_id(team))
        return

    # Slack also fires member_joined_channel for the bot's own join — skip it to avoid noise.
    if user == own_bot_user_id:
        return

    # Members of the team's own organization are internal teammates, not the external
    # participants these alerts surface — skip them.
    slack_user = resolve_slack_user(client, user)
    if resolve_posthog_user_for_slack(slack_user.get("email"), team):
        return

    verb = "joined" if joined else "left"
    message_kwargs: dict = {
        "channel": alert_channel,
        "text": f"<@{user}> {verb} <#{channel}>",
    }
    bot_display_name = settings_dict.get("slack_bot_display_name")
    bot_icon_url = settings_dict.get("slack_bot_icon_url")
    if bot_display_name:
        message_kwargs["username"] = bot_display_name
    if bot_icon_url:
        message_kwargs["icon_url"] = bot_icon_url

    try:
        client.chat_postMessage(**message_kwargs)
    except Exception:
        logger.warning(
            "slack_member_event_post_failed",
            team_id=_get_team_id(team),
            alert_channel=alert_channel,
            joined=joined,
        )


def handle_member_joined_channel(event: dict, team: Team, slack_team_id: str) -> None:
    """Handle a Slack 'member_joined_channel' event by alerting the configured channel."""
    # Resolve the bot identity once and share it with both the analytics event and the alert,
    # since a bot join always needs it for tracking regardless of the alert toggle.
    client = get_slack_client(team)
    own_bot_user_id = get_bot_user_id_cached(team, client)
    _track_bot_joined_channel(event, team, slack_team_id, own_bot_user_id=own_bot_user_id)
    _handle_member_event(event, team, joined=True, client=client, own_bot_user_id=own_bot_user_id)


def handle_member_left_channel(event: dict, team: Team, slack_team_id: str) -> None:
    """Handle a Slack 'member_left_channel' event by alerting the configured channel."""
    _handle_member_event(event, team, joined=False)
