"""Celery tasks for the conversations product."""

import html as html_mod
from email.utils import formataddr, make_msgid
from typing import Any, cast
from urllib.parse import quote, urlparse
from uuid import UUID

from django.core import mail
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

import requests
import structlog
from celery import shared_task

from posthog.models.comment import Comment as CommentModel
from posthog.models.instance_setting import get_instance_setting
from posthog.models.team import Team
from posthog.models.uploaded_media import UploadedMedia
from posthog.storage import object_storage

from products.conversations.backend.events import capture_ticket_status_changed
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
    TeamConversationsSlackConfig,
    TeamConversationsTeamsConfig,
)
from products.conversations.backend.models.constants import Status
from products.conversations.backend.models.ticket import Ticket
from products.conversations.backend.slack import (
    get_slack_client,
    handle_support_mention,
    handle_support_message,
    handle_support_reaction,
    resolve_slack_avatar_by_email,
)
from products.conversations.backend.support_teams import (
    get_bot_framework_token,
    get_bot_from_id,
    invalidate_bot_framework_token,
    is_trusted_teams_service_url,
)
from products.conversations.backend.teams import (
    _is_bot_mention,
    handle_teams_mention,
    handle_teams_message,
    send_teams_welcome_card,
)
from products.conversations.backend.teams_formatting import rich_content_to_teams_html

from .support_slack import SUPPORT_SLACK_ALLOWED_HOST_SUFFIXES, SUPPORT_SLACK_MAX_IMAGE_BYTES

logger = structlog.get_logger(__name__)
SUPPORTHOG_EVENT_IDEMPOTENCY_TTL_SECONDS = 6 * 60
SUPPORTHOG_EVENT_IDEMPOTENCY_KEY_PREFIX = "supporthog:slack:event:"
SUPPORTHOG_TEAMS_EVENT_IDEMPOTENCY_KEY_PREFIX = "supporthog:teams:event:"


def _is_duplicate_supporthog_event(event_id: str) -> bool:
    key = f"{SUPPORTHOG_EVENT_IDEMPOTENCY_KEY_PREFIX}{event_id}"
    return not cache.add(key, True, timeout=SUPPORTHOG_EVENT_IDEMPOTENCY_TTL_SECONDS)


def _is_duplicate_teams_event(activity_id: str) -> bool:
    key = f"{SUPPORTHOG_TEAMS_EVENT_IDEMPOTENCY_KEY_PREFIX}{activity_id}"
    return not cache.add(key, True, timeout=SUPPORTHOG_EVENT_IDEMPOTENCY_TTL_SECONDS)


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5)
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
    except Exception as e:
        logger.exception(
            "supporthog_event_handler_failed",
            event_type=event_type,
            error=str(e),
        )
        raise cast(Any, process_supporthog_event).retry(exc=e)


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5)
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

    if len(payload) > SUPPORT_SLACK_MAX_IMAGE_BYTES:
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


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=10)
def send_email_reply(
    ticket_id: str,
    team_id: int,
    comment_id: str,
    content: str,
    rich_content: dict | None,
    author_name: str,
) -> None:
    """Send a team member's reply to the customer via SMTP email."""
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.warning("email_reply_team_not_found", team_id=team_id)
        return

    try:
        ticket = Ticket.objects.select_related("email_config").get(id=ticket_id, team=team)
    except Ticket.DoesNotExist:
        logger.warning("email_reply_ticket_not_found", ticket_id=ticket_id)
        return

    config = ticket.email_config
    if not config:
        logger.warning("email_reply_no_config", team_id=team_id, ticket_id=ticket_id)
        return

    if not config.domain_verified:
        logger.warning("email_reply_domain_not_verified", team_id=team_id, domain=config.domain)
        return

    if not ticket.email_from:
        logger.warning("email_reply_no_customer_email", ticket_id=ticket_id)
        return

    # Build threading headers from the latest inbound message on this ticket
    latest_mapping = EmailMessageMapping.objects.filter(ticket=ticket, team=team).order_by("-created_at").first()
    headers: dict[str, str] = {}
    if latest_mapping:
        headers["In-Reply-To"] = latest_mapping.message_id
        # Collect all message IDs for References header
        all_ids = list(
            EmailMessageMapping.objects.filter(ticket=ticket, team=team)
            .order_by("created_at")
            .values_list("message_id", flat=True)
        )
        if all_ids:
            headers["References"] = " ".join(all_ids)

    # Generate a new Message-ID for the outbound email
    inbound_domain = get_instance_setting("CONVERSATIONS_EMAIL_INBOUND_DOMAIN") or config.domain
    outbound_message_id = make_msgid(domain=inbound_domain)
    headers["Message-ID"] = outbound_message_id

    # Build email body
    if rich_content:
        html_body = rich_content_to_html(rich_content)
        txt_body = rich_content_to_markdown(rich_content, include_images=False)
    else:
        txt_body = content
        html_body = f"<p>{html_mod.escape(content)}</p>"

    subject = ticket.email_subject or "Re: Your support request"
    if not subject.lower().startswith("re:"):
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
        logger.warning("email_reply_send_transient_failure", ticket_id=ticket_id, error=str(e))
        raise cast(Any, send_email_reply).retry(exc=e)
    except MailgunDomainNotRegistered:
        logger.exception(
            "email_reply_send_domain_not_registered",
            ticket_id=ticket_id,
            team_id=team_id,
            domain=config.domain,
        )
        config.mark_domain_unverified()
        return
    except (MailgunPermanentError, MailgunNotConfigured):
        logger.exception(
            "email_reply_send_permanent_failure",
            ticket_id=ticket_id,
            team_id=team_id,
            domain=config.domain,
        )
        return

    # Record the outbound message mapping for threading (best-effort, don't retry on failure)
    try:
        comment_obj = CommentModel.objects.get(id=comment_id, team=team)
        EmailMessageMapping.objects.create(
            message_id=outbound_message_id,
            team=team,
            ticket=ticket,
            comment=comment_obj,
        )
    except Exception:
        logger.exception("email_reply_mapping_failed", ticket_id=ticket_id, message_id=outbound_message_id)

    logger.info(
        "email_reply_sent",
        ticket_id=ticket_id,
        team_id=team_id,
        to=ticket.email_from,
        message_id=outbound_message_id,
    )


@shared_task(bind=True, ignore_result=True, max_retries=2, default_retry_delay=5)
def send_teams_welcome(self, activity: dict[str, Any]) -> None:
    """Post the proactive welcome card after the bot is added to a team.

    Required by Microsoft Teams Store certification policy 11.4.4.3. Runs in
    Celery so the Bot Framework webhook can ack within its 15s budget. We
    actually use the configured ``max_retries`` budget for transient transport
    failures (5xx, timeouts) — cert validators install and watch for the
    welcome card to appear, so silently dropping it would re-fail the review.
    Permanent failures (malformed activity, bot config missing) are not
    retried; ``send_teams_welcome_card`` returns ``True`` for those so we
    don't burn the retry budget on something a retry can't fix.
    """
    try:
        ok = send_teams_welcome_card(activity)
    except Exception as exc:
        logger.exception("supporthog_teams_welcome_failed", error=str(exc))
        raise cast(Any, self).retry(exc=exc)
    if not ok:
        raise cast(Any, self).retry(exc=Exception("teams_welcome_card_post_failed"))


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5)
def process_teams_event(activity: dict[str, Any], tenant_id: str, activity_id: str = "") -> None:
    """Process an inbound Teams Bot Framework activity."""

    if activity_id and _is_duplicate_teams_event(activity_id):
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

    try:
        if _is_bot_mention(activity):
            handle_teams_mention(activity, team, tenant_id)
        else:
            handle_teams_message(activity, team, tenant_id)
    except Exception as e:
        logger.exception("supporthog_teams_event_handler_failed", error=str(e))
        raise cast(Any, process_teams_event).retry(exc=e)


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5)
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


WAKE_SNOOZE_BATCH_SIZE = 100


@shared_task(ignore_result=True)
def wake_snoozed_tickets() -> None:
    """Reopen tickets whose snooze period has expired, in batches."""

    now = timezone.now()
    total = 0

    while True:
        with transaction.atomic():
            batch = list(
                Ticket.objects.select_for_update(skip_locked=True)
                .filter(snoozed_until__isnull=False, snoozed_until__lte=now)
                .order_by("snoozed_until")[:WAKE_SNOOZE_BATCH_SIZE]
            )
            if not batch:
                break

            for ticket in batch:
                old_status = ticket.status
                ticket.snoozed_until = None

                if old_status == Status.ON_HOLD:
                    ticket.status = Status.OPEN
                    ticket.save(update_fields=["status", "snoozed_until", "updated_at"])
                    try:
                        capture_ticket_status_changed(ticket, old_status, Status.OPEN)
                    except Exception:
                        logger.exception("wake_snoozed_ticket_event_failed", ticket_id=str(ticket.id))
                else:
                    ticket.save(update_fields=["snoozed_until", "updated_at"])

            total += len(batch)
            if len(batch) < WAKE_SNOOZE_BATCH_SIZE:
                break

    if total:
        logger.info("wake_snoozed_tickets_completed", count=total)
