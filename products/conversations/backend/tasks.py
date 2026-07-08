"""Celery tasks for the conversations product."""

import html as html_mod
import json
import uuid
from datetime import datetime, timedelta
from email.utils import formataddr
from typing import Any, cast
from urllib.parse import quote, urlparse
from uuid import UUID

from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError, models, transaction
from django.db.models import F
from django.db.models.fields.json import JSONField
from django.db.models.functions import Coalesce
from django.utils import timezone

import requests
import structlog
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.comment import Comment as CommentModel
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.team import Team
from posthog.models.uploaded_media import UploadedMedia
from posthog.scoping_audit import skip_team_scope_audit
from posthog.storage import object_storage

from products.conversations.backend.cache import NUDGE_DISMISS_TTL, suppress_nudge
from products.conversations.backend.events import (
    capture_sla_approaching,
    capture_sla_breached,
    capture_ticket_status_changed,
)
from products.conversations.backend.formatting import (
    extract_images_from_rich_content,
    rich_content_to_html,
    rich_content_to_markdown,
    rich_content_to_slack_payload,
)
from products.conversations.backend.mailgun import (
    MailgunDomainNotRegistered,
    MailgunNotConfigured,
    MailgunPermanentError,
    MailgunTransientError,
    send_mime,
)
from products.conversations.backend.models import (
    EmailMessageMapping,
    EmailOutboxMessage,
    GithubCommentMapping,
    TeamConversationsSlackConfig,
    TeamConversationsTeamsChannelSync,
    TeamConversationsTeamsConfig,
)
from products.conversations.backend.models.constants import SLA_MAX_WARNING_MINUTES, Channel, ChannelDetail, Status
from products.conversations.backend.models.ticket import Ticket
from products.conversations.backend.services.attachments import CONVERSATIONS_MAX_IMAGE_BYTES
from products.conversations.backend.slack import (
    TICKET_CONFIRM_ACTION_DISMISS,
    TICKET_CONFIRM_ACTION_OPEN,
    create_ticket_from_confirmation,
    get_bot_user_id,
    get_safe_ticket_emoji,
    get_slack_client,
    handle_member_joined_channel,
    handle_member_left_channel,
    handle_support_mention,
    handle_support_message,
    handle_support_reaction,
    resolve_slack_avatar_by_email,
    ticket_created_text,
)
from products.conversations.backend.support_teams import (
    get_bot_framework_token,
    get_bot_from_id,
    get_graph_token,
    invalidate_bot_framework_token,
    is_trusted_teams_service_url,
    store_teams_service_url,
)
from products.conversations.backend.teams import (
    GRAPH_API_BASE,
    _is_bot_mention,
    create_or_update_teams_ticket,
    graph_message_to_activity,
    graph_reply_to_activity,
    handle_teams_mention,
    handle_teams_message,
    is_shared_membership_type,
    parse_teams_root_message_id,
    post_help_card,
    post_teams_channel_message_via_graph,
)
from products.conversations.backend.teams_attachments import extract_teams_graph_images
from products.conversations.backend.teams_formatting import rich_content_to_teams_html

from .support_slack import SUPPORT_SLACK_ALLOWED_HOST_SUFFIXES

logger = structlog.get_logger(__name__)
SUPPORTHOG_EVENT_IDEMPOTENCY_TTL_SECONDS = 6 * 60
SUPPORTHOG_EVENT_IDEMPOTENCY_KEY_PREFIX = "supporthog:slack:event:"
SUPPORTHOG_TEAMS_EVENT_IDEMPOTENCY_KEY_PREFIX = "supporthog:teams:event:"
SUPPORTHOG_GITHUB_EVENT_IDEMPOTENCY_KEY_PREFIX = "supporthog:github:event:"


def _is_duplicate_supporthog_event(event_id: str) -> bool:
    key = f"{SUPPORTHOG_EVENT_IDEMPOTENCY_KEY_PREFIX}{event_id}"
    return not cache.add(key, True, timeout=SUPPORTHOG_EVENT_IDEMPOTENCY_TTL_SECONDS)


def is_duplicate_teams_event(activity_id: str) -> bool:
    """Atomic Redis-backed dedup keyed on Bot Framework ``activity.id``.

    Used both by ``process_teams_event`` (after dispatch) and by the webhook
    handler (before dispatch, for the welcome and help-reply paths). Bot
    Framework retries with the same ``activity.id`` for up to ~10 mins on
    5xx/timeouts, so any handler that produces side effects must guard.
    """
    key = f"{SUPPORTHOG_TEAMS_EVENT_IDEMPOTENCY_KEY_PREFIX}{activity_id}"
    return not cache.add(key, True, timeout=SUPPORTHOG_EVENT_IDEMPOTENCY_TTL_SECONDS)


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5)
@skip_team_scope_audit
def process_supporthog_event(event: dict[str, Any], slack_team_id: str, event_id: str | None = None) -> None:
    if event_id and _is_duplicate_supporthog_event(event_id):
        logger.info("supporthog_event_duplicate_skipped", event_id=event_id)
        return

    config = (
        TeamConversationsSlackConfig.objects.filter(slack_team_id=slack_team_id, slack_bot_token__isnull=False)
        .select_related("team")
        .first()
    )
    if not config:
        logger.warning("supporthog_no_team", slack_team_id=slack_team_id)
        return

    team = config.team
    support_settings = team.conversations_settings or {}
    if not support_settings.get("slack_enabled"):
        logger.info(
            "supporthog_support_not_configured",
            team_id=team.id,
            slack_team_id=slack_team_id,
        )
        return

    event_type = event.get("type")
    try:
        if event_type == "message":
            handle_support_message(event, team, slack_team_id)
        elif event_type == "app_mention":
            handle_support_mention(event, team, slack_team_id)
        elif event_type == "reaction_added":
            handle_support_reaction(event, team, slack_team_id)
        elif event_type == "member_joined_channel":
            handle_member_joined_channel(event, team, slack_team_id)
        elif event_type == "member_left_channel":
            handle_member_left_channel(event, team, slack_team_id)
    except Exception as e:
        logger.exception(
            "supporthog_event_handler_failed",
            event_type=event_type,
            error=str(e),
        )
        raise cast(Any, process_supporthog_event).retry(exc=e)


def _delete_supporthog_prompt(team: Team, channel: str, message_ts: str) -> None:
    """Delete the "open a ticket?" prompt message after a "No thanks" click.

    Best-effort: a failure here never blocks anything else.
    """
    if not channel or not message_ts:
        return
    try:
        get_slack_client(team).chat_delete(channel=channel, ts=message_ts)
    except Exception:
        logger.warning("supporthog_interactivity_prompt_delete_failed", exc_info=True)


def _update_supporthog_prompt(team: Team, channel: str, message_ts: str, text: str) -> None:
    """Replace the "open a ticket?" prompt in place with a final status line (buttons removed).

    Best-effort: a failure here never blocks the ticket creation that already ran.
    """
    if not channel or not message_ts:
        return
    try:
        get_slack_client(team).chat_update(
            channel=channel,
            ts=message_ts,
            text=text,
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
        )
    except Exception:
        logger.warning("supporthog_interactivity_prompt_update_failed", exc_info=True)


def _post_dismiss_acknowledgment(team: Team, channel: str, user: str, thread_ts: str) -> None:
    """Privately acknowledge a "No thanks" click, pointing the author at the other ways in.

    Ephemeral so only the person who clicked sees it; best-effort.
    """
    if not channel or not user:
        return
    emoji = get_safe_ticket_emoji(team.conversations_settings or {})
    try:
        client = get_slack_client(team)
        bot_id = get_bot_user_id(client)
        mention = f"<@{bot_id}>" if bot_id else "the SupportHog bot"
        client.chat_postEphemeral(
            channel=channel,
            user=user,
            thread_ts=thread_ts or None,
            text=f"Got it — if you change your mind, react with :{emoji}: or tag {mention}.",
        )
    except Exception:
        logger.warning("supporthog_interactivity_dismiss_ack_failed", exc_info=True)


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5)
@skip_team_scope_audit
def process_supporthog_interactivity(payload: dict[str, Any], slack_team_id: str) -> None:
    """Handle a button click from the opt-in "open a ticket?" confirmation prompt."""
    config = (
        TeamConversationsSlackConfig.objects.filter(slack_team_id=slack_team_id, slack_bot_token__isnull=False)
        .select_related("team")
        .first()
    )
    if not config:
        logger.warning("supporthog_interactivity_no_team", slack_team_id=slack_team_id)
        return

    team = config.team
    support_settings = team.conversations_settings or {}
    if not support_settings.get("slack_enabled"):
        return

    if payload.get("type") != "block_actions":
        return

    # The prompt message to delete: where the button was clicked.
    container = payload.get("container") or {}
    prompt_channel = (payload.get("channel") or {}).get("id") or container.get("channel_id") or ""
    prompt_ts = (payload.get("message") or {}).get("ts") or container.get("message_ts") or ""

    clicker = (payload.get("user") or {}).get("id", "")

    for action in payload.get("actions") or []:
        action_id = action.get("action_id")
        try:
            value = json.loads(action.get("value") or "{}")
        except (json.JSONDecodeError, TypeError):
            value = {}
        source_channel = value.get("channel", "")
        source_message_ts = value.get("message_ts", "")

        if action_id == TICKET_CONFIRM_ACTION_DISMISS:
            _delete_supporthog_prompt(team, prompt_channel, prompt_ts)
            _post_dismiss_acknowledgment(team, prompt_channel, clicker, source_message_ts)
            # Don't pester them again in this channel for a while.
            if clicker:
                suppress_nudge(team.pk, prompt_channel, clicker, NUDGE_DISMISS_TTL)
            return
        if action_id == TICKET_CONFIRM_ACTION_OPEN:
            ticket = None
            if source_channel and source_message_ts:
                try:
                    ticket = create_ticket_from_confirmation(
                        team=team,
                        slack_team_id=slack_team_id,
                        slack_channel_id=source_channel,
                        message_ts=source_message_ts,
                    )
                except Exception as e:
                    logger.exception("supporthog_interactivity_create_failed", error=str(e))
                    # Retry transient failures — the retried run redoes the whole handler,
                    # so the prompt still resolves on eventual success. Once retries are
                    # exhausted, fall through to the error update below rather than leaving
                    # the user staring at live buttons forever.
                    try:
                        raise cast(Any, process_supporthog_interactivity).retry(exc=e)
                    except MaxRetriesExceededError:
                        pass
            # Replace the prompt in place: a confirmation when we have a ticket (created or
            # already open), or an explicit error so a failed open never reads as success.
            # post_confirmation=False above means no separate confirmation was posted.
            if ticket:
                text = ticket_created_text(ticket)
            else:
                emoji = get_safe_ticket_emoji(support_settings)
                text = f":warning: Couldn't open a ticket — react with :{emoji}: or @mention us to try again."
            _update_supporthog_prompt(team, prompt_channel, prompt_ts, text)
            return


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5)
@skip_team_scope_audit
def post_reply_to_slack(
    ticket_id: str,
    team_id: int,
    content: str,
    rich_content: dict | None,
    author_name: str,
    slack_channel_id: str,
    slack_thread_ts: str,
    author_email: str = "",
) -> None:
    """Post a support agent's reply to the corresponding Slack thread."""

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.warning("slack_reply_team_not_found", team_id=team_id)
        return

    try:
        client = get_slack_client(team)
    except ValueError:
        logger.warning(
            "slack_reply_no_credentials",
            team_id=team_id,
        )
        return

    slack_text, slack_blocks = rich_content_to_slack_payload(rich_content, content, include_images=False)
    rich_images = extract_images_from_rich_content(rich_content)
    logger.info(
        "🧵 slack_reply_payload_prepared",
        ticket_id=ticket_id,
        team_id=team_id,
        has_text=bool(slack_text.strip()),
        has_blocks=bool(slack_blocks),
        image_count=len(rich_images),
    )

    support_settings = team.conversations_settings or {}
    bot_display_name = support_settings.get("slack_bot_display_name")
    bot_icon_url = support_settings.get("slack_bot_icon_url")

    # Resolve the replying user's Slack profile picture
    author_icon_url: str | None = None
    if author_email:
        author_icon_url = resolve_slack_avatar_by_email(client, author_email)

    icon_url = author_icon_url or bot_icon_url
    message_kwargs: dict = {
        "channel": slack_channel_id,
        "thread_ts": slack_thread_ts,
        "text": slack_text,
        "username": author_name or bot_display_name or "Support",
    }
    if icon_url:
        message_kwargs["icon_url"] = icon_url
    if slack_blocks:
        message_kwargs["blocks"] = slack_blocks

    try:
        if slack_text.strip() or slack_blocks:
            logger.info(
                "🧵 slack_reply_text_post_attempt",
                ticket_id=ticket_id,
                channel=slack_channel_id,
                thread_ts=slack_thread_ts,
                has_text=bool(slack_text.strip()),
                has_blocks=bool(slack_blocks),
            )
            client.chat_postMessage(**message_kwargs)
        else:
            logger.warning(
                "🧵 slack_reply_text_post_skipped_empty",
                ticket_id=ticket_id,
                channel=slack_channel_id,
                thread_ts=slack_thread_ts,
            )

        failed_image_urls: list[str] = []
        for image in rich_images:
            logger.info(
                "🖼️ slack_reply_image_upload_attempt",
                ticket_id=ticket_id,
                image_url=image.get("url"),
                image_alt=image.get("alt"),
            )
            image_bytes = _read_image_bytes_for_slack_upload(team_id, image.get("url", ""))
            if image_bytes is None:
                logger.warning("🖼️ slack_reply_image_upload_skipped", ticket_id=ticket_id, image_url=image.get("url"))
                failed_image_urls.append(image.get("url") or "")
                continue

            image_name = _filename_for_slack_image(image.get("alt"), image.get("url"))
            try:
                _upload_image_to_slack_thread(
                    client=client,
                    slack_channel_id=slack_channel_id,
                    slack_thread_ts=slack_thread_ts,
                    image_name=image_name,
                    image_bytes=image_bytes,
                )
            except Exception as image_error:
                logger.warning(
                    "🖼️ slack_reply_image_upload_failed",
                    ticket_id=ticket_id,
                    image_url=image.get("url"),
                    error=str(image_error),
                )
                failed_image_urls.append(image.get("url") or "")
            else:
                logger.info(
                    "🖼️ slack_reply_image_upload_succeeded",
                    ticket_id=ticket_id,
                    image_url=image.get("url"),
                    bytes_size=len(image_bytes),
                )

        # Fallback for missing Slack file scopes: keep images visible as links.
        if failed_image_urls:
            unique_urls = [url for url in dict.fromkeys(failed_image_urls) if url]
            if unique_urls:
                fallback_text = "Images:\n" + "\n".join(unique_urls)
                fallback_kwargs: dict = {
                    "channel": slack_channel_id,
                    "thread_ts": slack_thread_ts,
                    "text": fallback_text,
                    "username": author_name or bot_display_name or "Support",
                }
                if icon_url:
                    fallback_kwargs["icon_url"] = icon_url
                client.chat_postMessage(**fallback_kwargs)
                logger.warning(
                    "🖼️ slack_reply_image_upload_fallback_links_posted",
                    ticket_id=ticket_id,
                    channel=slack_channel_id,
                    fallback_count=len(unique_urls),
                )

        logger.info(
            "🧵 slack_reply_posted",
            ticket_id=ticket_id,
            channel=slack_channel_id,
            image_uploads=len(rich_images),
        )
    except Exception as e:
        logger.exception(
            "slack_reply_post_failed",
            ticket_id=ticket_id,
            error=str(e),
        )
        raise cast(Any, post_reply_to_slack).retry(exc=e)


def _filename_for_slack_image(alt: str | None, image_url: str | None) -> str:
    if alt and alt.strip():
        return alt.strip()
    if image_url:
        path = urlparse(image_url).path
        if path:
            name = path.rsplit("/", 1)[-1]
            if name:
                return name
    return "image"


def _upload_image_to_slack_thread(
    *,
    client,
    slack_channel_id: str,
    slack_thread_ts: str,
    image_name: str,
    image_bytes: bytes,
) -> None:
    # Slack deprecated files.upload; use external upload API flow.
    get_upload_url = client.api_call(
        api_method="files.getUploadURLExternal",
        params={
            "filename": image_name,
            "length": len(image_bytes),
        },
    )
    if not get_upload_url.get("ok"):
        raise ValueError(f"files.getUploadURLExternal failed: {get_upload_url.get('error')}")

    upload_url = get_upload_url.get("upload_url")
    file_id = get_upload_url.get("file_id")
    if not upload_url or not file_id:
        raise ValueError("files.getUploadURLExternal missing upload_url/file_id")
    if not _is_allowed_slack_upload_url(upload_url):
        raise ValueError("files.getUploadURLExternal returned disallowed upload URL")

    upload_response = requests.post(
        upload_url,
        data=image_bytes,
        headers={"Content-Type": "application/octet-stream"},
        timeout=10,
    )
    upload_response.raise_for_status()

    complete_upload = client.api_call(
        api_method="files.completeUploadExternal",
        json={
            "files": [{"id": file_id, "title": image_name}],
            "channel_id": slack_channel_id,
            "thread_ts": slack_thread_ts,
        },
    )
    if not complete_upload.get("ok"):
        raise ValueError(f"files.completeUploadExternal failed: {complete_upload.get('error')}")


def _is_allowed_slack_upload_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    return any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in SUPPORT_SLACK_ALLOWED_HOST_SUFFIXES)


def _read_image_bytes_for_slack_upload(team_id: int, image_url: str) -> bytes | None:
    if not image_url:
        return None

    parsed = urlparse(image_url)
    if not parsed.path.startswith("/uploaded_media/"):
        logger.warning("🖼️ slack_reply_image_not_uploaded_media", team_id=team_id, image_url=image_url)
        return None

    image_id = parsed.path.removeprefix("/uploaded_media/").strip("/")
    try:
        UUID(image_id)
    except ValueError:
        logger.warning("🖼️ slack_reply_image_invalid_uploaded_media_id", team_id=team_id, image_id=image_id)
        return None

    uploaded_media = UploadedMedia.objects.filter(id=image_id, team_id=team_id).first()
    if not uploaded_media or not uploaded_media.media_location:
        logger.warning(
            "🖼️ slack_reply_image_uploaded_media_not_found",
            team_id=team_id,
            image_id=image_id,
        )
        return None

    if not (uploaded_media.content_type or "").startswith("image/"):
        logger.warning("🖼️ slack_reply_image_invalid_content_type", team_id=team_id, image_id=image_id)
        return None

    try:
        payload = object_storage.read_bytes(uploaded_media.media_location)
    except Exception as e:
        logger.warning(
            "🖼️ slack_reply_image_read_storage_failed",
            team_id=team_id,
            image_id=image_id,
            error=str(e),
        )
        return None

    if payload is None:
        logger.warning(
            "🖼️ slack_reply_image_storage_returned_none",
            team_id=team_id,
            image_id=image_id,
        )
        return None

    if len(payload) > CONVERSATIONS_MAX_IMAGE_BYTES:
        logger.warning(
            "🖼️ slack_reply_image_too_large",
            team_id=team_id,
            image_id=image_id,
            size=len(payload),
        )
        return None

    logger.info(
        "🖼️ slack_reply_image_read_succeeded",
        team_id=team_id,
        image_id=image_id,
        bytes_size=len(payload),
    )
    return payload


# Outbound email outbox tuning. Durability lives in the Postgres outbox row, not
# the broker: a periodic sweeper re-drives pending rows until they send or hit the
# age cutoff, so an agent reply survives a multi-day Mailgun block.
EMAIL_OUTBOX_SEND_LOCK_SECONDS = 120  # app-level lease covering a single send attempt
EMAIL_OUTBOX_BACKOFF_BASE_SECONDS = 60
EMAIL_OUTBOX_BACKOFF_MAX_SECONDS = 3600  # cap retry spacing at ~1h during a long outage
EMAIL_OUTBOX_MAX_AGE = timedelta(days=5)  # give up past this (comfortably > a Fri-Mon block)
EMAIL_OUTBOX_FLUSH_BATCH_SIZE = 100


def _set_comment_delivery_status(team_id: int, comment_id: UUID, status_value: str) -> None:
    """Denormalize delivery status onto the comment's item_context so the agent UI can
    show a sending/failed badge. Uses a queryset update to avoid re-firing Comment signals.

    Merges at the DB level (JSONB ``||``) rather than read-modify-write: a concurrent
    edit to another key (e.g. an agent flipping ``is_private``) must not be clobbered.
    The dict values flow through ORM ``Value`` params, so this is fully parameterized.
    """
    merged = models.Func(
        Coalesce("item_context", models.Value({}, output_field=JSONField())),
        models.Value({"email_delivery_status": status_value}, output_field=JSONField()),
        template="%(expressions)s",
        arg_joiner=" || ",
        output_field=JSONField(),
    )
    CommentModel.objects.filter(id=comment_id, team_id=team_id).update(item_context=merged)


def _mark_outbox_sent(outbox: EmailOutboxMessage) -> None:
    outbox.status = EmailOutboxMessage.Status.SENT
    outbox.sent_at = timezone.now()
    outbox.locked_until = None
    outbox.last_error = ""
    outbox.save(update_fields=["status", "sent_at", "locked_until", "last_error", "updated_at"])
    # Record the outbound message mapping for threading (best-effort).
    try:
        EmailMessageMapping.objects.get_or_create(
            message_id=outbox.message_id,
            team_id=outbox.team_id,
            defaults={"ticket_id": outbox.ticket_id, "comment_id": outbox.comment_id},
        )
    except Exception:
        logger.exception("email_reply_mapping_failed", outbox_id=str(outbox.id), message_id=outbox.message_id)
    _set_comment_delivery_status(outbox.team_id, outbox.comment_id, "sent")


def _mark_outbox_failed(outbox: EmailOutboxMessage, error: str) -> None:
    outbox.status = EmailOutboxMessage.Status.FAILED_PERMANENT
    outbox.last_error = error[:2000]
    outbox.locked_until = None
    outbox.save(update_fields=["status", "last_error", "locked_until", "updated_at"])
    _set_comment_delivery_status(outbox.team_id, outbox.comment_id, "failed")


def _schedule_outbox_retry(outbox: EmailOutboxMessage, error: str) -> None:
    outbox.attempts += 1
    backoff = min(
        EMAIL_OUTBOX_BACKOFF_BASE_SECONDS * (2 ** min(outbox.attempts, 16)),
        EMAIL_OUTBOX_BACKOFF_MAX_SECONDS,
    )
    outbox.next_attempt_at = timezone.now() + timedelta(seconds=backoff)
    outbox.last_error = error[:2000]
    outbox.locked_until = None
    outbox.save(update_fields=["attempts", "next_attempt_at", "last_error", "locked_until", "updated_at"])
    _set_comment_delivery_status(outbox.team_id, outbox.comment_id, "sending")


def _process_outbox_row(outbox: EmailOutboxMessage) -> None:
    """Render and send one already-claimed outbox row, recording the outcome.

    The caller must have taken the lease (locked_until) before calling this. Uses the
    row's stored message_id so every attempt is byte-stable for threading and dedup.
    """
    ticket = outbox.ticket
    config = ticket.email_config
    comment = outbox.comment

    if not config:
        _mark_outbox_failed(outbox, "no email config")
        return
    if not config.domain_verified:
        _mark_outbox_failed(outbox, f"domain {config.domain} not verified")
        return
    if not ticket.email_from:
        _mark_outbox_failed(outbox, "no customer email")
        return

    # Defense-in-depth: never send out a comment that itself arrived via inbound
    # email — mirrors the from_email signal guard at the last mile, so a future
    # regression in outbox enqueueing can't echo inbound mail back to recipients.
    if isinstance(comment.item_context, dict) and comment.item_context.get("from_email"):
        _mark_outbox_failed(outbox, "comment originated from inbound email")
        return

    author_name = ""
    if comment.created_by:
        author_name = (
            f"{comment.created_by.first_name} {comment.created_by.last_name}".strip() or comment.created_by.email
        )

    # Build threading headers from the latest inbound message on this ticket
    latest_mapping = (
        EmailMessageMapping.objects.filter(ticket_id=ticket.id, team_id=outbox.team_id).order_by("-created_at").first()
    )
    headers: dict[str, str] = {"Message-ID": outbox.message_id}
    if latest_mapping:
        headers["In-Reply-To"] = latest_mapping.message_id
        all_ids = list(
            EmailMessageMapping.objects.filter(ticket_id=ticket.id, team_id=outbox.team_id)
            .order_by("created_at")
            .values_list("message_id", flat=True)
        )
        if all_ids:
            headers["References"] = " ".join(all_ids)

    if comment.rich_content:
        html_body = rich_content_to_html(comment.rich_content)
        txt_body = rich_content_to_markdown(comment.rich_content, include_images=False)
    else:
        txt_body = comment.content or ""
        html_body = f"<p>{html_mod.escape(comment.content or '')}</p>"

    subject = ticket.email_subject or "Your support request"
    is_reply = latest_mapping is not None
    if is_reply and not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    from_email = formataddr((config.from_name or author_name, config.from_email))

    email_message = mail.EmailMultiAlternatives(
        subject=subject,
        body=txt_body,
        from_email=from_email,
        to=[ticket.email_from],
        cc=ticket.cc_participants or [],
        headers=headers,
    )
    email_message.attach_alternative(html_body, "text/html")

    recipients = [ticket.email_from, *(ticket.cc_participants or [])]
    mime_bytes = email_message.message().as_bytes(linesep="\r\n")

    try:
        send_mime(config.domain, mime_bytes, recipients=recipients)
    except MailgunTransientError as e:
        # Retriable — keep the row pending and back off; the sweeper re-drives it.
        logger.warning("email_reply_send_transient_failure", outbox_id=str(outbox.id), error=str(e))
        _schedule_outbox_retry(outbox, str(e))
        return
    except MailgunDomainNotRegistered:
        logger.exception("email_reply_send_domain_not_registered", outbox_id=str(outbox.id), domain=config.domain)
        config.mark_domain_unverified()
        _mark_outbox_failed(outbox, "domain not registered with Mailgun")
        return
    except (MailgunPermanentError, MailgunNotConfigured) as e:
        logger.exception("email_reply_send_permanent_failure", outbox_id=str(outbox.id), domain=config.domain)
        _mark_outbox_failed(outbox, str(e))
        return

    _mark_outbox_sent(outbox)
    logger.info(
        "email_reply_sent",
        outbox_id=str(outbox.id),
        team_id=outbox.team_id,
        to=ticket.email_from,
        message_id=outbox.message_id,
    )


def _claim_outbox_row(outbox_id: str) -> EmailOutboxMessage | None:
    """Take the app-level lease on a single pending, due, unlocked row. Returns the
    locked row, or None if it's gone, terminal, or already being worked by someone else.
    """
    now = timezone.now()
    with transaction.atomic():
        # of=("self",) locks only the outbox row — the select_related joins reach a
        # nullable email_config FK, and Postgres can't FOR UPDATE an outer-join side.
        outbox = (
            EmailOutboxMessage.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("ticket", "ticket__email_config", "comment", "comment__created_by")
            .filter(id=outbox_id, status=EmailOutboxMessage.Status.PENDING)
            .filter(models.Q(locked_until__isnull=True) | models.Q(locked_until__lte=now))
            .first()
        )
        if outbox is None:
            return None
        outbox.locked_until = now + timedelta(seconds=EMAIL_OUTBOX_SEND_LOCK_SECONDS)
        outbox.save(update_fields=["locked_until", "updated_at"])
        return outbox


@shared_task(ignore_result=True)
@skip_team_scope_audit
def send_email_reply(outbox_id: str) -> None:
    """Attempt one delivery of a queued outbound email reply.

    Idempotent per outbox row: a no-op if the row is already sent/failed or currently
    leased. Durability does not depend on this task running — if the broker drops it,
    ``flush_pending_email_replies`` re-drives the row from Postgres.
    """
    outbox = _claim_outbox_row(outbox_id)
    if outbox is None:
        return
    _process_outbox_row(outbox)


@shared_task(ignore_result=True)
@skip_team_scope_audit
def flush_pending_email_replies() -> None:
    """Re-drive pending outbound email replies on a schedule.

    This is what survives a multi-day Mailgun outage: the broker only ever holds
    short-lived tasks, while the durable state is the Postgres outbox row swept here.
    Rows older than EMAIL_OUTBOX_MAX_AGE are given up (visibly, as failed_permanent).

    Bounded to one batch per run; the every-minute schedule drains any larger backlog
    over successive runs, keeping a single invocation short.
    """
    now = timezone.now()
    cutoff = now - EMAIL_OUTBOX_MAX_AGE

    with transaction.atomic():
        batch = list(
            EmailOutboxMessage.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("ticket", "ticket__email_config", "comment", "comment__created_by")
            .filter(status=EmailOutboxMessage.Status.PENDING, next_attempt_at__lte=now)
            .filter(models.Q(locked_until__isnull=True) | models.Q(locked_until__lte=now))
            .order_by("next_attempt_at")[:EMAIL_OUTBOX_FLUSH_BATCH_SIZE]
        )
        for outbox in batch:
            outbox.locked_until = now + timedelta(seconds=EMAIL_OUTBOX_SEND_LOCK_SECONDS)
            outbox.save(update_fields=["locked_until", "updated_at"])

    if not batch:
        return

    for outbox in batch:
        if outbox.created_at < cutoff:
            logger.warning("email_reply_outbox_expired", outbox_id=str(outbox.id), attempts=outbox.attempts)
            _mark_outbox_failed(outbox, "exceeded max delivery age")
            continue
        _process_outbox_row(outbox)

    logger.info("flush_pending_email_replies_completed", count=len(batch))


@shared_task(bind=True, ignore_result=True, max_retries=2, default_retry_delay=5)
def send_teams_help(self, activity: dict[str, Any], reply: bool = False) -> None:
    """Post the help/welcome adaptive card (Teams Store cert 11.4.4.3).

    ``reply=True`` lands the card as a thread reply (response to a "Hi"/"Help"
    command); ``reply=False`` is the proactive welcome on install.
    """
    # Capture the tenant's serviceUrl as early as install — this is often the
    # only inbound activity a pure-ambient shared-channel tenant ever sends, and
    # the poller needs it to post confirmation cards / sync agent replies.
    tenant_id = ((activity.get("channelData") or {}).get("tenant") or {}).get("id") or ""
    try:
        store_teams_service_url(tenant_id, activity.get("serviceUrl") or "")
    except Exception:
        pass

    try:
        ok = post_help_card(
            activity,
            log_prefix="teams_help_reply" if reply else "teams_welcome",
            reply=reply,
        )
    except Exception as exc:
        logger.exception("supporthog_teams_help_failed", error=str(exc), reply=reply)
        raise cast(Any, self).retry(exc=exc)
    if not ok:
        raise cast(Any, self).retry(exc=Exception("teams_help_card_post_failed"))


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5)
@skip_team_scope_audit
def process_teams_event(activity: dict[str, Any], tenant_id: str, activity_id: str = "") -> None:
    """Process an inbound Teams Bot Framework activity."""

    if activity_id and is_duplicate_teams_event(activity_id):
        logger.info("supporthog_teams_event_duplicate_skipped", activity_id=activity_id)
        return

    config = (
        TeamConversationsTeamsConfig.objects.filter(teams_tenant_id=tenant_id, teams_graph_access_token__isnull=False)
        .select_related("team")
        .first()
    )
    if not config:
        logger.warning("supporthog_teams_no_team", tenant_id=tenant_id)
        return

    team = config.team
    support_settings = team.conversations_settings or {}
    if not support_settings.get("teams_enabled"):
        logger.info("supporthog_teams_not_configured", team_id=team.id, tenant_id=tenant_id)
        return

    # Capture the tenant's Bot Framework serviceUrl from any inbound activity so
    # the shared-channel poller (which has no inbound activity) can post
    # confirmation cards and route agent replies for polled tickets.
    try:
        store_teams_service_url(tenant_id, activity.get("serviceUrl") or "")
    except Exception:
        logger.warning("store_teams_service_url_failed", team_id=team.id, tenant_id=tenant_id)

    try:
        if _is_bot_mention(activity):
            handle_teams_mention(activity, team, tenant_id)
        else:
            handle_teams_message(activity, team, tenant_id)
    except Exception as e:
        logger.exception("supporthog_teams_event_handler_failed", error=str(e))
        raise cast(Any, process_teams_event).retry(exc=e)


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5)
@skip_team_scope_audit
def post_reply_to_teams(
    ticket_id: str,
    team_id: int,
    content: str,
    rich_content: dict | None,
    author_name: str,
    teams_service_url: str,
    teams_conversation_id: str,
) -> None:
    """Post a support agent's reply to the corresponding Teams conversation thread."""
    if not is_trusted_teams_service_url(teams_service_url):
        logger.warning("teams_reply_untrusted_service_url", ticket_id=ticket_id, service_url=teams_service_url)
        return

    if not Team.objects.filter(id=team_id).exists():
        logger.warning("teams_reply_team_not_found", team_id=team_id)
        return

    try:
        bot_token = get_bot_framework_token()
        bot_from_id = get_bot_from_id()
    except ValueError:
        logger.warning("teams_reply_no_bot_token", team_id=team_id)
        return

    reply_html = rich_content_to_teams_html(rich_content, content)
    display_text = f"{author_name}: {content[:200]}" if author_name else content[:200]

    payload: dict[str, Any] = {
        "type": "message",
        "from": {"id": bot_from_id},
        "conversation": {"id": teams_conversation_id},
        "text": reply_html,
        # Teams accepts only "plain", "markdown", or "xml" for textFormat — not "html".
        # With "markdown", Teams passes through the common HTML tags we emit
        # (<b>, <i>, <a>, <ul>, <li>, <p>, <br>, <code>, <pre>, <img>).
        "textFormat": "markdown",
        "summary": display_text,
    }

    encoded_conversation_id = quote(teams_conversation_id, safe="")
    url = f"{teams_service_url.rstrip('/')}/v3/conversations/{encoded_conversation_id}/activities"
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {bot_token}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        if resp.status_code == 401:
            invalidate_bot_framework_token()
        if resp.status_code not in (200, 201):
            logger.warning(
                "teams_reply_post_failed",
                ticket_id=ticket_id,
                status=resp.status_code,
                body=resp.text[:500],
                url=url,
            )
            raise cast(Any, post_reply_to_teams).retry(
                exc=Exception(f"Teams reply failed with status {resp.status_code}")
            )

        logger.info("teams_reply_posted", ticket_id=ticket_id, conversation_id=teams_conversation_id)
    except requests.RequestException as e:
        logger.exception("teams_reply_post_error", ticket_id=ticket_id, error=str(e))
        raise cast(Any, post_reply_to_teams).retry(exc=e)


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5)
@skip_team_scope_audit
def post_reply_to_teams_via_graph(
    ticket_id: str,
    team_id: int,
    teams_team_id: str,
    channel_id: str,
    root_message_id: str,
    content: str,
    rich_content: dict | None,
    author_name: str,
) -> None:
    """Post a support agent's reply into a shared Teams channel thread via Graph.

    Shared channels can't be written to over the bot connector, so replies go through
    Graph with the delegated admin token (same path the poller reads with).
    """
    team = Team.objects.filter(id=team_id).first()
    if not team:
        logger.warning("teams_graph_reply_team_not_found", team_id=team_id)
        return

    reply_html = rich_content_to_teams_html(rich_content, content)
    if author_name:
        reply_html = f"<p><b>{html_mod.escape(author_name)}</b></p>{reply_html}"

    status, _message_id = post_teams_channel_message_via_graph(
        team=team,
        teams_team_id=teams_team_id,
        channel_id=channel_id,
        html=reply_html,
        reply_to_message_id=root_message_id,
        log_context={"ticket_id": ticket_id},
    )
    if status in (200, 201):
        logger.info("teams_graph_reply_posted", ticket_id=ticket_id, channel_id=channel_id)
        return

    # Retry only transient failures (network/no-token=0, throttling, 5xx). Permanent
    # ones — 401/403 (token/consent), 404 (thread gone), 400 — won't self-heal and
    # would just burn the retry budget, so log and drop.
    if status == 0 or status == 429 or status >= 500:
        raise cast(Any, post_reply_to_teams_via_graph).retry(
            exc=Exception(f"Teams Graph reply transient failure (status {status})")
        )
    logger.warning("teams_graph_reply_permanent_failure", ticket_id=ticket_id, status=status)


def _shared_channel_entries(support_settings: dict) -> list[dict]:
    """Configured channels the poller pulls (shared/unknownFutureValue, not standard/private)."""
    entries = support_settings.get("teams_channels")
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict) and is_shared_membership_type(e.get("membership_type"))]


def _parse_graph_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None


# Bound the work per invocation so priming a long-lived channel (the first delta
# walk returns the channel's full history before the deltaLink) can't hammer Graph
# in a single run. Remaining pages resume on subsequent every-minute runs.
TEAMS_DELTA_MAX_PAGES_PER_RUN = 20
TEAMS_DELTA_REQUEST_TIMEOUT_SECONDS = 30
TEAMS_REPLIES_MAX_PAGES_PER_TICKET = 5
# Graph list-replies caps $top at 50; larger values return 400 Bad Request.
TEAMS_REPLIES_PAGE_SIZE = 50
# Cap the number of tickets whose threads we poll per channel per run.
# Oldest-synced tickets are polled first so the sweep round-robins through
# the backlog across successive every-minute runs.
TEAMS_REPLIES_MAX_TICKETS_PER_CHANNEL = 20
# Only poll threads on tickets created within this window.
TEAMS_REPLIES_TICKET_AGE_DAYS = 30
# Re-scan a small window behind the watermark so replies aren't silently dropped when
# Graph's createdDateTime and our stored watermark disagree by a few seconds (clock skew
# between the polling worker and Graph). Dedup downstream makes the overlap harmless.
TEAMS_REPLIES_WATERMARK_LOOKBACK = timedelta(minutes=5)
# Safety cap on delta-triggered reply fetches per run. Delta only surfaces threads with
# fresh activity (so this is naturally traffic-bounded), but a pathological burst across
# many threads shouldn't fan out into unbounded Graph /replies calls in a single run.
TEAMS_REPLIES_MAX_DELTA_TRIGGERED_PER_CHANNEL = 50


def _sync_one_ticket_thread_replies(
    *,
    team: Team,
    tenant_id: str,
    token: str,
    teams_team_id: str,
    channel_id: str,
    service_url: str,
    ticket: Ticket,
) -> None:
    """Ingest new thread replies for one shared-channel ticket via Graph."""
    root_message_id = parse_teams_root_message_id(ticket.teams_conversation_id)
    if not root_message_id:
        logger.debug(
            "poll_teams_shared_channel_replies_no_root",
            team_id=team.id,
            channel_id=channel_id,
            ticket_id=str(ticket.id),
        )
        return

    raw_watermark = ticket.teams_thread_replies_synced_at or ticket.created_at
    watermark = raw_watermark - TEAMS_REPLIES_WATERMARK_LOOKBACK
    latest_synced_at = ticket.teams_thread_replies_synced_at

    url: str | None = (
        f"{GRAPH_API_BASE}/teams/{teams_team_id}/channels/{channel_id}/messages/{root_message_id}/replies"
        f"?$top={TEAMS_REPLIES_PAGE_SIZE}"
    )
    headers = {"Authorization": f"Bearer {token}"}
    pages = 0
    replies_fetched = 0
    # "matched" = reply resolved to this ticket (covers both new comments and dedup
    # hits); create_or_update_teams_ticket doesn't distinguish, so we don't claim to.
    replies_matched = 0

    while url and pages < TEAMS_REPLIES_MAX_PAGES_PER_TICKET:
        pages += 1
        resp = requests.get(url, headers=headers, timeout=TEAMS_DELTA_REQUEST_TIMEOUT_SECONDS)

        if resp.status_code in (401, 402, 403, 404, 429):
            logger.warning(
                "poll_teams_shared_channel_replies_denied",
                team_id=team.id,
                channel_id=channel_id,
                ticket_id=str(ticket.id),
                status=resp.status_code,
            )
            return
        if resp.status_code != 200:
            logger.warning(
                "poll_teams_shared_channel_replies_error",
                team_id=team.id,
                channel_id=channel_id,
                ticket_id=str(ticket.id),
                root_message_id=root_message_id,
                status=resp.status_code,
                body=resp.text[:500],
            )
            return

        data = resp.json()
        replies = data.get("value") or []
        replies_fetched += len(replies)

        page_had_failure = False
        for reply in replies:
            msg_created = _parse_graph_datetime(reply.get("createdDateTime"))
            if msg_created and msg_created < watermark:
                continue

            activity = graph_reply_to_activity(reply, channel_id, root_message_id, service_url)
            if activity is None:
                continue

            reply_images = extract_teams_graph_images(reply, team, teams_team_id, channel_id, token)
            try:
                result = create_or_update_teams_ticket(
                    team=team,
                    activity=activity,
                    tenant_id=tenant_id,
                    is_thread_reply=True,
                    images=reply_images,
                )
            except Exception:
                logger.exception(
                    "poll_teams_shared_channel_reply_ingest_failed",
                    team_id=team.id,
                    channel_id=channel_id,
                    ticket_id=str(ticket.id),
                )
                page_had_failure = True
                continue

            if result:
                replies_matched += 1
            if result and msg_created and (latest_synced_at is None or msg_created > latest_synced_at):
                latest_synced_at = msg_created

        if page_had_failure:
            break

        url = data.get("@odata.nextLink")

    if replies_fetched:
        logger.info(
            "poll_teams_shared_channel_replies_synced",
            team_id=team.id,
            channel_id=channel_id,
            ticket_id=str(ticket.id),
            root_message_id=root_message_id,
            replies_fetched=replies_fetched,
            replies_matched=replies_matched,
            watermark=raw_watermark.isoformat(),
        )

    new_watermark = latest_synced_at or timezone.now()
    if new_watermark != ticket.teams_thread_replies_synced_at:
        Ticket.objects.filter(id=ticket.id, team=team).update(teams_thread_replies_synced_at=new_watermark)


def _sync_ticket_thread_replies_safe(
    *,
    team: Team,
    tenant_id: str,
    token: str,
    teams_team_id: str,
    channel_id: str,
    service_url: str,
    ticket: Ticket,
) -> None:
    """Run ``_sync_one_ticket_thread_replies`` with the standard error handling."""
    try:
        _sync_one_ticket_thread_replies(
            team=team,
            tenant_id=tenant_id,
            token=token,
            teams_team_id=teams_team_id,
            channel_id=channel_id,
            service_url=service_url,
            ticket=ticket,
        )
    except requests.RequestException:
        logger.warning(
            "poll_teams_shared_channel_replies_network_error",
            team_id=team.id,
            channel_id=channel_id,
            ticket_id=str(ticket.id),
        )
    except Exception:
        logger.exception(
            "poll_teams_shared_channel_replies_unexpected",
            team_id=team.id,
            channel_id=channel_id,
            ticket_id=str(ticket.id),
        )


def _sync_shared_channel_thread_replies(
    *,
    team: Team,
    tenant_id: str,
    token: str,
    teams_team_id: str,
    channel_id: str,
    service_url: str,
    surfaced_conversation_ids: set[str] | None = None,
) -> None:
    """Pull new thread replies for every Teams ticket in a shared channel.

    ``surfaced_conversation_ids`` are threads delta saw activity on this run; their
    tickets are always synced (on top of the round-robin selection) so a fresh reply
    is pulled the same minute even when the ticket isn't in the oldest-synced window.
    """
    sync = TeamConversationsTeamsChannelSync.objects.for_team(team.id).filter(channel_id=channel_id).first()
    if not sync or not sync.primed:
        logger.debug(
            "poll_teams_shared_channel_replies_not_primed",
            team_id=team.id,
            channel_id=channel_id,
            has_sync=bool(sync),
        )
        return

    age_cutoff = timezone.now() - timedelta(days=TEAMS_REPLIES_TICKET_AGE_DAYS)
    tickets = list(
        Ticket.objects.filter(
            team=team,
            channel_source=Channel.TEAMS,
            teams_channel_id=channel_id,
            created_at__gte=age_cutoff,
        )
        .exclude(teams_conversation_id__isnull=True)
        .exclude(teams_conversation_id="")
        .exclude(status=Status.RESOLVED)
        .order_by(F("teams_thread_replies_synced_at").asc(nulls_first=True))[:TEAMS_REPLIES_MAX_TICKETS_PER_CHANNEL]
    )

    selected_ids = {ticket.id for ticket in tickets}
    delta_triggered = 0
    if surfaced_conversation_ids:
        surfaced_tickets = (
            Ticket.objects.filter(
                team=team,
                channel_source=Channel.TEAMS,
                teams_channel_id=channel_id,
                teams_conversation_id__in=surfaced_conversation_ids,
            )
            .exclude(status=Status.RESOLVED)
            .exclude(id__in=selected_ids)
            .order_by(F("teams_thread_replies_synced_at").asc(nulls_first=True))[
                :TEAMS_REPLIES_MAX_DELTA_TRIGGERED_PER_CHANNEL
            ]
        )
        for ticket in surfaced_tickets:
            tickets.append(ticket)
            delta_triggered += 1

    logger.debug(
        "poll_teams_shared_channel_replies_tickets_selected",
        team_id=team.id,
        channel_id=channel_id,
        tickets_selected=len(tickets),
        delta_triggered=delta_triggered,
    )

    for ticket in tickets:
        _sync_ticket_thread_replies_safe(
            team=team,
            tenant_id=tenant_id,
            token=token,
            teams_team_id=teams_team_id,
            channel_id=channel_id,
            service_url=service_url,
            ticket=ticket,
        )


def _poll_one_shared_channel(
    *,
    team: Team,
    tenant_id: str,
    token: str,
    teams_team_id: str,
    channel_id: str,
    service_url: str,
) -> set[str]:
    """Pull new top-level messages for one shared channel via Graph messages/delta.

    First run for a channel primes the delta cursor without ingesting (no history
    dump); subsequent runs map each new root message onto the existing ticket path.
    Idempotency is handled by ``create_or_update_teams_ticket`` (dedup on
    channel + normalized conversation id), so re-delivering a message is a no-op.

    Returns the set of conversation ids whose root message delta re-surfaced this run,
    so the caller can prioritize their thread-reply sync.
    """
    sync, created = TeamConversationsTeamsChannelSync.objects.for_team(team.id).get_or_create(
        channel_id=channel_id,
        defaults={"team": team, "teams_team_id": teams_team_id},
    )

    # On first encounter, verify via Graph that the channel is actually shared.
    # conversations_settings is client-mutable, so we don't trust its
    # membership_type — we confirm from the authoritative source before polling.
    # Graph returns "unknownFutureValue" for shared channels in some tenants, so we
    # reject only explicit standard/private channels rather than requiring "shared".
    if created:
        ch_resp = requests.get(
            f"{GRAPH_API_BASE}/teams/{teams_team_id}/channels/{channel_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=TEAMS_DELTA_REQUEST_TIMEOUT_SECONDS,
        )
        if ch_resp.status_code != 200 or not is_shared_membership_type(ch_resp.json().get("membershipType")):
            logger.warning(
                "poll_teams_shared_channel_not_shared",
                team_id=team.id,
                channel_id=channel_id,
                status=ch_resp.status_code,
            )
            sync.delete()
            return set()

    url: str | None = sync.delta_link or (
        f"{GRAPH_API_BASE}/teams/{teams_team_id}/channels/{channel_id}/messages/delta"
    )
    headers = {"Authorization": f"Bearer {token}"}

    new_delta_link: str | None = None
    latest_message_at: datetime | None = None
    pages = 0
    # Root messages delta re-surfaced this run (Graph bumps a root's lastModifiedDateTime
    # when a thread reply lands). Their tickets get a targeted reply sync below so the
    # reply is pulled the same minute, independent of the round-robin reply sweep.
    surfaced_conversation_ids: set[str] = set()

    while url and pages < TEAMS_DELTA_MAX_PAGES_PER_RUN:
        pages += 1
        resp = requests.get(url, headers=headers, timeout=TEAMS_DELTA_REQUEST_TIMEOUT_SECONDS)

        if resp.status_code == 410:
            # Delta token expired/invalid: reset and re-prime on the next run.
            sync.delta_link = None
            sync.primed = False
            sync.last_polled_at = timezone.now()
            sync.save(update_fields=["delta_link", "primed", "last_polled_at", "updated_at"])
            logger.info("poll_teams_shared_channel_resync", team_id=team.id, channel_id=channel_id)
            return set()
        if resp.status_code == 429:
            logger.warning("poll_teams_shared_channel_throttled", team_id=team.id, channel_id=channel_id)
            return set()
        if resp.status_code in (401, 402, 403):
            # 401: token rejected (next run refreshes if stale). 402: metered/payment
            # gate. 403: lost channel membership / missing scope. Skip, don't crash.
            logger.warning(
                "poll_teams_shared_channel_denied",
                team_id=team.id,
                channel_id=channel_id,
                status=resp.status_code,
            )
            return set()
        if resp.status_code != 200:
            logger.warning(
                "poll_teams_shared_channel_error",
                team_id=team.id,
                channel_id=channel_id,
                status=resp.status_code,
            )
            return set()

        data = resp.json()
        messages = data.get("value") or []

        if sync.primed:
            for msg in messages:
                msg_created = _parse_graph_datetime(msg.get("createdDateTime"))
                if msg_created and (latest_message_at is None or msg_created > latest_message_at):
                    latest_message_at = msg_created
                activity = graph_message_to_activity(msg, channel_id, service_url)
                if activity is None:
                    continue
                conversation_id = (activity.get("conversation") or {}).get("id")
                if conversation_id:
                    surfaced_conversation_ids.add(conversation_id)
                images = extract_teams_graph_images(msg, team, teams_team_id, channel_id, token)
                try:
                    create_or_update_teams_ticket(
                        team=team,
                        activity=activity,
                        tenant_id=tenant_id,
                        is_thread_reply=False,
                        channel_detail=ChannelDetail.TEAMS_CHANNEL_MESSAGE,
                        # Shared channel: confirm via Graph (bot connector can't post here),
                        # reusing the token we already hold for the delta read.
                        graph_post_context={"teams_team_id": teams_team_id, "token": token},
                        images=images,
                    )
                except Exception:
                    logger.exception(
                        "poll_teams_shared_channel_ingest_failed",
                        team_id=team.id,
                        channel_id=channel_id,
                    )

        delta_link = data.get("@odata.deltaLink")
        next_link = data.get("@odata.nextLink")
        if delta_link:
            new_delta_link = delta_link
            url = None
        else:
            url = next_link

    update_fields = ["last_polled_at", "updated_at"]
    sync.last_polled_at = timezone.now()

    if new_delta_link:
        sync.delta_link = new_delta_link
        update_fields.append("delta_link")
        if not sync.primed:
            sync.primed = True
            update_fields.append("primed")
    elif url:
        # Hit the per-run page budget mid-walk; resume from this nextLink next run.
        sync.delta_link = url
        update_fields.append("delta_link")

    if latest_message_at and (sync.last_message_at is None or latest_message_at > sync.last_message_at):
        sync.last_message_at = latest_message_at
        update_fields.append("last_message_at")

    sync.save(update_fields=update_fields)

    # Delta only surfaces roots, never the replies themselves. A re-surfaced root signals
    # thread activity, so the caller passes these ids to the reply sweep to pull their
    # replies the same minute regardless of the round-robin selection.
    return surfaced_conversation_ids


@shared_task(ignore_result=True)
@skip_team_scope_audit
def poll_team_shared_channels(team_id: int) -> None:
    """Poll every configured shared channel for one team."""
    team = Team.objects.filter(id=team_id).first()
    if not team:
        return

    support_settings = team.conversations_settings or {}
    if not support_settings.get("teams_enabled"):
        return

    shared_channels = _shared_channel_entries(support_settings)
    if not shared_channels:
        return

    config = TeamConversationsTeamsConfig.objects.filter(team=team).first()
    tenant_id = config.teams_tenant_id if config else None
    if not tenant_id:
        logger.warning("poll_teams_shared_channels_no_tenant", team_id=team_id)
        return

    try:
        token = get_graph_token(team)
    except ValueError:
        logger.warning("poll_teams_shared_channels_no_token", team_id=team_id)
        return

    # serviceUrl is captured from inbound webhook activities (install/mention).
    # Empty until then: polled tickets still get created, but confirmation cards
    # and agent-reply sync stay dormant until the first inbound activity fills it.
    service_url = (config.teams_service_url or "") if config else ""

    for entry in shared_channels:
        channel_id = entry.get("channel_id")
        teams_team_id = entry.get("team_id")
        if not channel_id or not teams_team_id:
            continue
        try:
            surfaced_conversation_ids = _poll_one_shared_channel(
                team=team,
                tenant_id=tenant_id,
                token=token,
                teams_team_id=teams_team_id,
                channel_id=channel_id,
                service_url=service_url,
            )
            _sync_shared_channel_thread_replies(
                team=team,
                tenant_id=tenant_id,
                token=token,
                teams_team_id=teams_team_id,
                channel_id=channel_id,
                service_url=service_url,
                surfaced_conversation_ids=surfaced_conversation_ids,
            )
        except requests.RequestException:
            logger.warning("poll_teams_shared_channel_network_error", team_id=team_id, channel_id=channel_id)
        except Exception:
            logger.exception("poll_teams_shared_channel_unexpected", team_id=team_id, channel_id=channel_id)


@shared_task(ignore_result=True)
@skip_team_scope_audit
def poll_teams_shared_channels() -> None:
    """Fan out per-team shared-channel polling.

    Shared/private Teams channels never push ambient (non-@mention) messages over
    the bot webhook, so we pull them from Graph on a schedule. One subtask per team
    keeps a slow or rate-limited tenant from blocking the others.
    """
    configs = (
        TeamConversationsTeamsConfig.objects.filter(teams_graph_access_token__isnull=False)
        .select_related("team")
        .only("team__id", "team__conversations_settings", "teams_tenant_id")
    )

    team_ids: list[int] = []
    for config in configs:
        support_settings = config.team.conversations_settings or {}
        if not support_settings.get("teams_enabled"):
            continue
        if _shared_channel_entries(support_settings):
            team_ids.append(config.team_id)

    for team_id in team_ids:
        poll_team_shared_channels.delay(team_id)

    if team_ids:
        logger.info("poll_teams_shared_channels_fanout", team_count=len(team_ids))


WAKE_SNOOZE_BATCH_SIZE = 100


def _log_snooze_expired(ticket: Ticket, old_status: str, old_snoozed_until: datetime | None) -> None:
    """Record the system snooze-expiry (and reopen, unless already open) in the activity log."""

    changes = [
        Change(
            type="Ticket",
            field="snoozed_until",
            before=old_snoozed_until.isoformat() if old_snoozed_until else None,
            after=None,
            action="changed",
        )
    ]
    if old_status not in (Status.OPEN, Status.NEW):
        changes.append(Change(type="Ticket", field="status", before=old_status, after=Status.OPEN, action="changed"))

    try:
        log_activity(
            organization_id=ticket.team.organization_id,
            team_id=ticket.team_id,
            user=None,  # system actor — distinguishes auto-expiry from a manual unsnooze
            was_impersonated=False,
            item_id=str(ticket.id),
            scope="Ticket",
            activity="updated",
            detail=Detail(name=f"Ticket #{ticket.ticket_number}", changes=changes),
        )
    except Exception:
        logger.exception("wake_snoozed_ticket_activity_log_failed", ticket_id=str(ticket.id))


@shared_task(ignore_result=True)
def wake_snoozed_tickets() -> None:
    """Reopen tickets whose snooze period has expired, in batches."""

    now = timezone.now()
    total = 0

    while True:
        with transaction.atomic():
            batch = list(
                Ticket.objects.select_for_update(skip_locked=True, of=("self",))
                .select_related("team")
                .filter(snoozed_until__isnull=False, snoozed_until__lte=now)
                .order_by("snoozed_until")[:WAKE_SNOOZE_BATCH_SIZE]
            )
            if not batch:
                break

            for ticket in batch:
                old_status = ticket.status
                old_snoozed_until = ticket.snoozed_until
                ticket.snoozed_until = None

                # An expiring snooze reopens the ticket, unless it's already active (open or
                # new) — then there's just the snooze to clear, no status change.
                if old_status not in (Status.OPEN, Status.NEW):
                    ticket.status = Status.OPEN
                    ticket.save(update_fields=["status", "snoozed_until", "updated_at"])
                    try:
                        capture_ticket_status_changed(ticket, old_status, Status.OPEN, actor_type="system")
                    except Exception:
                        logger.exception("wake_snoozed_ticket_event_failed", ticket_id=str(ticket.id))
                else:
                    ticket.save(update_fields=["snoozed_until", "updated_at"])

                _log_snooze_expired(ticket, old_status, old_snoozed_until)

            total += len(batch)
            if len(batch) < WAKE_SNOOZE_BATCH_SIZE:
                break

    if total:
        logger.info("wake_snoozed_tickets_completed", count=total)


SLA_SWEEP_BATCH_SIZE = 100


def _sla_warning_offsets(ticket: Ticket) -> list[int]:
    """Warning offsets for a ticket: its own, else the team default, sanitized."""
    raw = ticket.sla_warning_minutes or (ticket.team.conversations_settings or {}).get("sla_warning_minutes") or []
    if not isinstance(raw, list):
        return []
    return sorted(
        {int(o) for o in raw if isinstance(o, int | float) and 1 <= o <= SLA_MAX_WARNING_MINUTES}, reverse=True
    )


def _emit_sla_events_for_ticket(ticket: Ticket, now: datetime) -> bool:
    """Emit due SLA events for one ticket; returns whether dedup markers changed.

    Markers are trusted only when stamped for the current deadline, so an SLA
    reset (new sla_due_at) re-arms both warnings and the breach event.
    """
    assert ticket.sla_due_at is not None
    due_key = ticket.sla_due_at.isoformat()
    markers = ticket.sla_events_sent if isinstance(ticket.sla_events_sent, dict) else {}
    if markers.get("due_at") != due_key:
        markers = {"due_at": due_key, "warned_minutes": [], "breached": False}

    if now >= ticket.sla_due_at:
        if markers.get("breached"):
            return False
        # Warnings that weren't emitted in time (e.g. worker downtime) are moot once breached.
        markers["breached"] = True
        ticket.sla_events_sent = markers
        ticket.save(update_fields=["sla_events_sent"])
        try:
            capture_sla_breached(ticket, now)
        except Exception:
            logger.exception("sla_breached_event_failed", ticket_id=str(ticket.id))
        return True

    warned = {int(m) for m in markers.get("warned_minutes") or []}
    crossed = [
        offset
        for offset in _sla_warning_offsets(ticket)
        if offset not in warned and now >= ticket.sla_due_at - timedelta(minutes=offset)
    ]
    if not crossed:
        return False

    # If several thresholds were crossed at once (catch-up after downtime), alert only for
    # the nearest one but mark them all, so a recovering worker doesn't send an alert storm.
    markers["warned_minutes"] = sorted(warned | set(crossed))
    ticket.sla_events_sent = markers
    ticket.save(update_fields=["sla_events_sent"])
    try:
        capture_sla_approaching(ticket, min(crossed), now)
    except Exception:
        logger.exception("sla_approaching_event_failed", ticket_id=str(ticket.id))
    return True


@shared_task(ignore_result=True)
def emit_ticket_sla_events() -> None:
    """Emit $conversation_sla_approaching / $conversation_sla_breached for tickets nearing
    or past their SLA deadline, so workflows can trigger alerts on them."""

    now = timezone.now()
    horizon = now + timedelta(minutes=SLA_MAX_WARNING_MINUTES)
    total = 0
    last_key: tuple[datetime, uuid.UUID] | None = None

    # Keyset pagination: processed rows still match the filter (unlike the snooze wake),
    # so advance a (sla_due_at, id) cursor instead of re-reading from the start.
    while True:
        with transaction.atomic():
            queryset = (
                Ticket.objects.select_for_update(skip_locked=True, of=("self",))
                .select_related("team")
                .filter(sla_due_at__isnull=False, sla_due_at__lte=horizon)
                .exclude(status=Status.RESOLVED)
                .order_by("sla_due_at", "id")
            )
            if last_key is not None:
                queryset = queryset.filter(
                    models.Q(sla_due_at__gt=last_key[0]) | models.Q(sla_due_at=last_key[0], id__gt=last_key[1])
                )
            batch = list(queryset[:SLA_SWEEP_BATCH_SIZE])
            if not batch:
                break

            for ticket in batch:
                if _emit_sla_events_for_ticket(ticket, now):
                    total += 1

            last_key = (batch[-1].sla_due_at, batch[-1].id)

        if len(batch) < SLA_SWEEP_BATCH_SIZE:
            break

    if total:
        logger.info("emit_ticket_sla_events_completed", count=total)


# ---------------------------------------------------------------------------
# GitHub Issues channel
# ---------------------------------------------------------------------------


def _is_duplicate_github_event(delivery_id: str) -> bool:
    key = f"{SUPPORTHOG_GITHUB_EVENT_IDEMPOTENCY_KEY_PREFIX}{delivery_id}"
    return cache.get(key) is not None


def _mark_github_event_processed(delivery_id: str) -> None:
    key = f"{SUPPORTHOG_GITHUB_EVENT_IDEMPOTENCY_KEY_PREFIX}{delivery_id}"
    cache.set(key, True, timeout=SUPPORTHOG_EVENT_IDEMPOTENCY_TTL_SECONDS)


def _find_github_ticket(team_id: int, repo: str, issue_number: int) -> Ticket | None:
    return Ticket.objects.filter(
        team_id=team_id,
        github_repo=repo,
        github_issue_number=issue_number,
    ).first()


def _get_or_create_github_ticket(team: Team, repo: str, issue_number: int, payload: dict[str, Any]) -> Ticket:
    """Find or create a ticket for a GitHub issue, safe against concurrent calls.

    Uses transaction.atomic() + the DB unique constraint
    posthog_con_github_issue_uniq to guarantee exactly one ticket per issue.
    """
    existing = _find_github_ticket(team.id, repo, issue_number)
    if existing:
        return existing

    issue = payload.get("issue", {})
    sender = payload.get("sender", {})
    issue_author = issue.get("user", {}).get("login", sender.get("login", ""))
    title = issue.get("title", "")

    try:
        with transaction.atomic():
            ticket = Ticket.objects.create_with_number(
                team=team,
                channel_source="github",
                channel_detail="github_issue",
                widget_session_id="",
                distinct_id=f"github:{issue_author}" if issue_author else "github:unknown",
                status=Status.NEW,
                anonymous_traits={"name": issue_author, "github_login": issue_author},
                github_repo=repo,
                github_issue_number=issue_number,
                unread_team_count=0,
                # Created from a signature-validated GitHub webhook — platform-attested identity.
                identity_verified=True,
            )

            if title:
                CommentModel.objects.create(
                    team=team,
                    scope="conversations_ticket",
                    item_id=str(ticket.id),
                    content=f"**{title}**",
                    item_context={"author_type": "customer", "is_private": False, "from_github": True},
                )

            return ticket
    except IntegrityError:
        existing = _find_github_ticket(team.id, repo, issue_number)
        if existing:
            return existing
        raise


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5)
@skip_team_scope_audit
def process_github_event(
    event_type: str,
    action: str,
    payload: dict[str, Any],
    delivery_id: str,
    team_id: int,
    repo: str,
) -> None:
    """Process an inbound GitHub webhook event for the Issues channel."""
    if delivery_id and _is_duplicate_github_event(delivery_id):
        logger.info("github_event_duplicate_skipped", delivery_id=delivery_id)
        return

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.warning("github_event_team_not_found", team_id=team_id)
        return

    settings_dict = team.conversations_settings or {}
    if not settings_dict.get("github_enabled"):
        return

    allowed_repos: list[str] = settings_dict.get("github_repos", [])
    if repo not in allowed_repos:
        logger.info("github_event_repo_not_monitored", repo=repo, team_id=team_id)
        return

    try:
        if event_type == "issues":
            _handle_github_issue_event(team, repo, action, payload)
        elif event_type == "issue_comment":
            _handle_github_comment_event(team, repo, action, payload)
    except Exception as e:
        logger.exception("github_event_handler_failed", event_type=event_type, action=action, error=str(e))
        raise cast(Any, process_github_event).retry(exc=e)

    if delivery_id:
        _mark_github_event_processed(delivery_id)


def _handle_github_issue_event(team: Team, repo: str, action: str, payload: dict[str, Any]) -> None:
    issue = payload.get("issue", {})
    issue_number = issue.get("number")
    if not issue_number:
        return

    if action == "opened":
        existing = _find_github_ticket(team.id, repo, issue_number)
        if existing:
            return

        ticket = _get_or_create_github_ticket(team, repo, issue_number, payload)

        # For "opened" events we have the full body — replace the title-only
        # comment that _get_or_create_github_ticket may have created with a
        # richer version including the issue body.
        sender = payload.get("sender", {})
        author_login = sender.get("login", "")
        title = issue.get("title", "")
        body = issue.get("body", "") or ""

        if body:
            first_comment = (
                CommentModel.objects.filter(team=team, scope="conversations_ticket", item_id=str(ticket.id))
                .order_by("created_at")
                .first()
            )
            if first_comment:
                first_comment.content = f"**{title}**\n\n{body}"[:50_000]
                first_comment.item_context = {
                    **(first_comment.item_context or {}),
                    "github_login": author_login,
                    "github_issue_title": title,
                }
                first_comment.save(update_fields=["content", "item_context"])

        ticket.unread_team_count = 1
        ticket.save(update_fields=["unread_team_count", "updated_at"])

    elif action in ("closed", "reopened"):
        existing = _find_github_ticket(team.id, repo, issue_number)
        if not existing:
            return

        # Reject stale/replayed payloads: skip if the issue event is older
        # than the ticket's last update (guards against replay after cache TTL)
        issue_updated_at = issue.get("updated_at")
        if issue_updated_at and existing.updated_at:
            try:
                from datetime import datetime

                event_ts = datetime.fromisoformat(issue_updated_at.replace("Z", "+00:00"))
                if event_ts < existing.updated_at:
                    logger.info(
                        "github_event_stale_status_change",
                        action=action,
                        ticket_id=str(existing.id),
                        event_ts=issue_updated_at,
                    )
                    return
            except (ValueError, TypeError):
                pass

        new_status = Status.RESOLVED if action == "closed" else Status.OPEN
        if existing.status == new_status:
            return

        old_status = existing.status
        existing.status = new_status
        existing.save(update_fields=["status", "updated_at"])
        try:
            capture_ticket_status_changed(existing, old_status, new_status, actor_type="external")
        except Exception:
            logger.exception("github_event_status_change_event_failed", ticket_id=str(existing.id))


def _handle_github_comment_event(team: Team, repo: str, action: str, payload: dict[str, Any]) -> None:
    if action != "created":
        return

    issue = payload.get("issue", {})
    comment_data = payload.get("comment", {})
    issue_number = issue.get("number")
    comment_id = comment_data.get("id")
    if not issue_number or not comment_id:
        return

    if GithubCommentMapping.objects.filter(github_comment_id=comment_id, team=team).exists():
        return

    # Comments posted via our GitHub App installation token carry
    # performed_via_github_app — skip these to avoid echoing our own replies.
    # The post_reply_to_github task will record the mapping once it completes.
    if comment_data.get("performed_via_github_app"):
        return

    ticket = _find_github_ticket(team.id, repo, issue_number)
    if not ticket:
        ticket = _get_or_create_github_ticket(team, repo, issue_number, payload)

    comment_author = comment_data.get("user", {}).get("login", "")
    body = comment_data.get("body", "") or ""

    item_context: dict[str, Any] = {
        "author_type": "customer",
        "is_private": False,
        "from_github": True,
        "github_login": comment_author,
        "github_comment_id": comment_id,
    }

    try:
        with transaction.atomic():
            comment = CommentModel.objects.create(
                team=team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content=body[:50_000],
                item_context=item_context,
            )

            GithubCommentMapping.objects.create(
                github_comment_id=comment_id,
                team=team,
                ticket=ticket,
                comment=comment,
            )
    except IntegrityError:
        # unique_github_comment_per_team — another worker already created this mapping
        return

    Ticket.objects.filter(id=ticket.id, team=team).update(
        unread_team_count=models.F("unread_team_count") + 1,
    )


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5)
@skip_team_scope_audit
def post_reply_to_github(
    ticket_id: str,
    team_id: int,
    content: str,
    rich_content: dict | None,
    author_name: str,
) -> None:
    """Post a support agent's reply to the corresponding GitHub issue."""
    from posthog.models.integration import GitHubIntegration

    try:
        ticket = Ticket.objects.get(id=ticket_id, team_id=team_id)
    except Ticket.DoesNotExist:
        logger.warning("github_reply_ticket_not_found", ticket_id=ticket_id)
        return

    if not ticket.github_repo or not ticket.github_issue_number:
        logger.warning("github_reply_missing_issue_info", ticket_id=ticket_id)
        return

    try:
        github = GitHubIntegration.first_for_team_repository(team_id, ticket.github_repo, source="conversations")
    except GitHubRateLimitError as e:
        # The access probe hit GitHub's limit — retry the reply later rather than dropping it.
        logger.warning("github_reply_rate_limited", ticket_id=ticket_id)
        raise cast(Any, post_reply_to_github).retry(exc=e, countdown=min(e.retry_after or 60, 600))
    if not github:
        logger.warning("github_reply_no_integration", team_id=team_id, repo=ticket.github_repo)
        return

    if rich_content:
        reply_text = rich_content_to_markdown(rich_content, include_images=True)
    else:
        reply_text = content

    if author_name:
        reply_text = f"**{author_name}** replied:\n\n{reply_text}"

    try:
        resp = github.api_request(
            "POST",
            f"/repos/{ticket.github_repo}/issues/{ticket.github_issue_number}/comments",
            json_body={"body": reply_text},
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            logger.warning(
                "github_reply_post_failed",
                ticket_id=ticket_id,
                status=resp.status_code,
                body=resp.text[:500],
            )
            raise cast(Any, post_reply_to_github).retry(
                exc=Exception(f"GitHub reply failed with status {resp.status_code}")
            )

        # Record the comment ID so the inbound webhook handler skips it
        resp_data = resp.json()
        gh_comment_id = resp_data.get("id")
        if gh_comment_id:
            GithubCommentMapping.objects.get_or_create(
                github_comment_id=gh_comment_id,
                team_id=team_id,
                defaults={"ticket": ticket, "comment": None},
            )

        logger.info("github_reply_posted", ticket_id=ticket_id, repo=ticket.github_repo)
    except GitHubRateLimitError as e:
        logger.warning("github_reply_rate_limited", ticket_id=ticket_id)
        raise cast(Any, post_reply_to_github).retry(exc=e, countdown=min(e.retry_after or 60, 600))
    except (GitHubIntegrationError, requests.RequestException) as e:
        logger.exception("github_reply_post_error", ticket_id=ticket_id, error=str(e))
        raise cast(Any, post_reply_to_github).retry(exc=e)


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5)
@skip_team_scope_audit
def create_github_issue(
    team_id: int,
    integration_id: int,
    repo: str,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> dict[str, Any] | None:
    """Create a GitHub issue and a linked Ticket."""
    from posthog.models.integration import GitHubIntegration, Integration

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.warning("github_create_issue_team_not_found", team_id=team_id)
        return None

    try:
        integration = Integration.objects.get(id=integration_id, team=team, kind="github")
    except Integration.DoesNotExist:
        logger.warning("github_create_issue_integration_not_found", integration_id=integration_id)
        return None

    github = GitHubIntegration(integration, source="conversations")

    try:
        issue_data = github.create_issue({"title": title, "body": body, "repository": repo, "labels": labels})
    except GitHubRateLimitError as e:
        logger.warning("github_create_issue_rate_limited", repo=repo)
        raise cast(Any, create_github_issue).retry(exc=e, countdown=min(e.retry_after or 60, 600))
    except GitHubIntegrationError as e:
        logger.exception("github_create_issue_failed", repo=repo, error=str(e))
        raise cast(Any, create_github_issue).retry(exc=e)

    issue_number = issue_data.get("number")

    ticket = Ticket.objects.create_with_number(
        team=team,
        channel_source="github",
        channel_detail="github_issue",
        widget_session_id="",
        distinct_id="",
        status=Status.OPEN,
        github_repo=repo,
        github_issue_number=issue_number,
        # Outbound issue opened by the team — there's no external party whose identity we verified,
        # so leave it unknown rather than claiming a verification that never happened.
        identity_verified=None,
    )

    CommentModel.objects.create(
        team=team,
        scope="conversations_ticket",
        item_id=str(ticket.id),
        content=f"**{title}**\n\n{body}" if body else f"**{title}**",
        item_context={"author_type": "customer", "is_private": False, "from_github": True},
    )

    logger.info("github_issue_created", ticket_id=str(ticket.id), repo=repo, issue_number=issue_number)
    return {"ticket_id": str(ticket.id), "issue_number": issue_number}
