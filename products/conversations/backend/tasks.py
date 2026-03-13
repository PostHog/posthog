"""Celery tasks for the conversations product."""

from typing import Any, cast
from urllib.parse import urlparse
from uuid import UUID

from django.core.cache import cache

import structlog
from celery import shared_task

from posthog.models.team import Team
from posthog.models.uploaded_media import UploadedMedia
from posthog.security.outbound_proxy import external_requests
from posthog.storage import object_storage

from products.conversations.backend.formatting import extract_images_from_rich_content, rich_content_to_slack_payload
from products.conversations.backend.slack import get_slack_client

from .support_slack import SUPPORT_SLACK_ALLOWED_HOST_SUFFIXES, SUPPORT_SLACK_MAX_IMAGE_BYTES

logger = structlog.get_logger(__name__)
SUPPORTHOG_EVENT_IDEMPOTENCY_TTL_SECONDS = 6 * 60
SUPPORTHOG_EVENT_IDEMPOTENCY_KEY_PREFIX = "supporthog:slack:event:"


def _is_duplicate_supporthog_event(event_id: str) -> bool:
    key = f"{SUPPORTHOG_EVENT_IDEMPOTENCY_KEY_PREFIX}{event_id}"
    return not cache.add(key, True, timeout=SUPPORTHOG_EVENT_IDEMPOTENCY_TTL_SECONDS)


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5)
def process_supporthog_event(event: dict[str, Any], slack_team_id: str, event_id: str | None = None) -> None:
    from products.conversations.backend.slack import (
        handle_support_mention,
        handle_support_message,
        handle_support_reaction,
    )

    if event_id and _is_duplicate_supporthog_event(event_id):
        logger.info("supporthog_event_duplicate_skipped", event_id=event_id)
        return

    from products.conversations.backend.models import TeamConversationsSlackConfig

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

    # Build message kwargs with optional avatar
    message_kwargs: dict = {
        "channel": slack_channel_id,
        "thread_ts": slack_thread_ts,
        "text": slack_text,
        "username": author_name or "Support",
    }
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
                client.chat_postMessage(
                    channel=slack_channel_id,
                    thread_ts=slack_thread_ts,
                    text=fallback_text,
                    username=author_name or "Support",
                )
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

    upload_response = external_requests.post(
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
def send_conversation_email(
    ticket_id: str,
    comment_id: str,
    team_id: int,
    content: str,
    rich_content: dict | None,
) -> None:
    """Send a support agent's reply to the customer via email using existing SMTP settings."""
    from django.conf import settings as django_settings
    from django.core import mail
    from django.core.mail.backends.smtp import EmailBackend
    from django.utils.module_loading import import_string

    from posthog.models.instance_setting import get_instance_setting

    from products.conversations.backend.formatting import rich_content_to_html
    from products.conversations.backend.models import EmailMessageMapping, TeamConversationsEmailConfig, Ticket

    try:
        ticket = Ticket.objects.select_related("team").get(id=ticket_id, team_id=team_id)
    except Ticket.DoesNotExist:
        logger.warning("email_reply_ticket_not_found", ticket_id=ticket_id)
        return

    if not ticket.email_from:
        logger.warning("email_reply_no_recipient", ticket_id=ticket_id)
        return

    try:
        config = TeamConversationsEmailConfig.objects.get(team_id=team_id)
    except TeamConversationsEmailConfig.DoesNotExist:
        logger.warning("email_reply_no_config", team_id=team_id)
        return

    # Build threading headers
    thread_mappings = list(
        EmailMessageMapping.objects.filter(team_id=team_id, ticket_id=ticket_id)
        .order_by("created_at")
        .values_list("message_id", flat=True)
    )

    # Find the most recent customer message for In-Reply-To
    latest_customer_mapping = (
        EmailMessageMapping.objects.filter(
            team_id=team_id, ticket_id=ticket_id, comment__isnull=False, comment__item_context__author_type="customer"
        )
        .order_by("-created_at")
        .first()
    )

    generated_message_id = f"<conv-{ticket_id}-{comment_id}@{config.domain}>"

    headers = {"Message-ID": generated_message_id}
    if latest_customer_mapping:
        headers["In-Reply-To"] = latest_customer_mapping.message_id
    if thread_mappings:
        headers["References"] = " ".join(thread_mappings)

    subject = f"Re: {ticket.email_subject}" if ticket.email_subject else "Re: Support request"
    from_email = f'"{config.from_name}" <{config.from_email}>'

    # Build HTML body from rich_content
    html_body = rich_content_to_html(rich_content) if rich_content else None

    msg = mail.EmailMultiAlternatives(
        subject=subject,
        body=content,
        from_email=from_email,
        to=[ticket.email_from],
        headers=headers,
    )

    if html_body:
        msg.attach_alternative(html_body, "text/html")

    try:
        klass = import_string(django_settings.EMAIL_BACKEND) if django_settings.EMAIL_BACKEND else EmailBackend
        connection = klass(
            host=get_instance_setting("EMAIL_HOST"),
            port=get_instance_setting("EMAIL_PORT"),
            username=get_instance_setting("EMAIL_HOST_USER"),
            password=get_instance_setting("EMAIL_HOST_PASSWORD"),
            use_tls=get_instance_setting("EMAIL_USE_TLS"),
            use_ssl=get_instance_setting("EMAIL_USE_SSL"),
        )
        connection.open()
        connection.send_messages([msg])
        connection.close()
    except Exception:
        logger.exception("email_reply_smtp_failed", ticket_id=ticket_id, team_id=team_id)
        raise

    # Record the outbound message ID for threading
    from posthog.models.comment import Comment as CommentModel

    comment_obj = CommentModel.objects.filter(id=comment_id).first()
    EmailMessageMapping.objects.create(
        message_id=generated_message_id,
        team_id=team_id,
        ticket=ticket,
        comment=comment_obj,
    )

    logger.info(
        "email_reply_sent",
        ticket_id=ticket_id,
        team_id=team_id,
        to=ticket.email_from,
        message_id=generated_message_id,
    )
