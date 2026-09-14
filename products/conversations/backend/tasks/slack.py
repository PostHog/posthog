"""Slack inbound events, interactivity, and outbound replies."""

import json
from typing import Any, Literal, cast, get_args
from urllib.parse import urlparse
from uuid import UUID

from django.core.cache import cache
from django.utils import timezone

import requests
import structlog
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from slack_sdk.errors import SlackApiError

from posthog.comment.formatting import extract_images_from_rich_content, rich_content_to_slack_payload
from posthog.helpers.slack_identity import resolve_slack_avatar_by_email
from posthog.models.team import Team
from posthog.models.uploaded_media import UploadedMedia
from posthog.scoping_audit import skip_team_scope_audit
from posthog.storage import object_storage

from products.conversations.backend.cache import NUDGE_DISMISS_TTL, suppress_nudge
from products.conversations.backend.models import (
    ConversationInboundEvent,
    ConversationInboundEventSource,
    TeamConversationsSlackConfig,
)
from products.conversations.backend.models.inbound_event import INBOUND_ERROR_MAX_LENGTH
from products.conversations.backend.models.ticket import Ticket
from products.conversations.backend.services.attachments import CONVERSATIONS_MAX_IMAGE_BYTES
from products.conversations.backend.services.inbound_events import (
    INBOUND_SWEEP_BATCH_SIZE,
    InboundClaim,
    TransientInboundError,
    claim_inbound_event,
    cleanup_inbound_payloads,
    complete_inbound_event,
    delete_inbound_tombstones,
    drain_inbound_retention,
    due_inbound_event_ids,
    fail_inbound_event,
    inbound_claim_scope,
    inbound_event_payload_event,
    record_inbound_queue_metrics,
    schedule_inbound_retry,
)
from products.conversations.backend.slack import (
    TICKET_CONFIRM_ACTION_DISMISS,
    TICKET_CONFIRM_ACTION_OPEN,
    NudgeClassifierVerdict,
    NudgeFunnelVerdict,
    SlackConfirmationNeedsRetry,
    capture_nudge_event,
    create_ticket_from_confirmation,
    get_bot_user_id,
    get_safe_ticket_emoji,
    get_slack_client,
    handle_member_joined_channel,
    handle_member_left_channel,
    handle_support_mention,
    handle_support_message,
    handle_support_reaction,
    nudge_event_properties,
    ticket_created_text,
)

from ..support_slack import SUPPORT_SLACK_ALLOWED_HOST_SUFFIXES, supporthog_missing_file_scopes

logger = structlog.get_logger(__name__)
SUPPORTHOG_EVENT_IDEMPOTENCY_TTL_SECONDS = 6 * 60
SUPPORTHOG_EVENT_IDEMPOTENCY_KEY_PREFIX = "supporthog:slack:event:"
PromptUpdateResult = Literal["updated", "missing", "transient", "permanent"]
_PERMANENT_PROMPT_UPDATE_ERROR_CODES = frozenset(
    {
        "account_inactive",
        "cannot_update_message",
        "cant_update_message",
        "channel_not_found",
        "invalid_auth",
        "is_archived",
        "message_not_found",
        "msg_too_long",
        "not_in_channel",
        "token_revoked",
    }
)


def _is_duplicate_supporthog_event(event_id: str) -> bool:
    key = f"{SUPPORTHOG_EVENT_IDEMPOTENCY_KEY_PREFIX}{event_id}"
    return not cache.add(key, True, timeout=SUPPORTHOG_EVENT_IDEMPOTENCY_TTL_SECONDS)


def _slack_config_for_workspace(
    slack_team_id: str, *, receipt_team_id: int | None = None
) -> TeamConversationsSlackConfig | None:
    config = (
        TeamConversationsSlackConfig.objects.filter(
            slack_team_id=slack_team_id,
            slack_bot_token__isnull=False,
        )
        .select_related("team")
        .first()
    )
    if config is None or receipt_team_id is None:
        return config
    config_root_team_id = config.team.parent_team_id or config.team_id
    return config if config_root_team_id == receipt_team_id else None


def _handle_supporthog_event(event: dict[str, Any], team: Team, slack_team_id: str) -> None:
    event_type = event.get("type")
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


def wake_inbound_event(row: ConversationInboundEvent, *, countdown: int | None = None) -> bool:
    task = (
        process_supporthog_event_receipt
        if row.source == ConversationInboundEventSource.SLACK_EVENTS
        else process_supporthog_interactivity_receipt
    )
    kwargs = {"inbound_event_id": str(row.id)}
    try:
        # retry=False: the receipt is already committed, so a hung broker must not
        # stall the Slack ack. The minute sweeper re-drives pending rows.
        apply_kwargs: dict[str, Any] = {"kwargs": kwargs, "retry": False}
        if countdown is not None:
            apply_kwargs["countdown"] = countdown
        cast(Any, task).apply_async(**apply_kwargs)
    except Exception:
        logger.exception("inbound_event_redrive_failed", inbound_event_id=str(row.id), source=row.source)
        return False
    return True


def _retry_inbound_claim(claim: InboundClaim, *, error_code: str, error: str) -> None:
    if not claim.allow_retry:
        fail_inbound_event(claim, error_code=error_code, error=error)
        return
    delay = schedule_inbound_retry(claim, error_code=error_code, error=error)
    if delay is not None:
        wake_inbound_event(claim.event, countdown=delay)


def _process_event_from_receipt(inbound_event_id: str) -> None:
    claim = claim_inbound_event(inbound_event_id)
    if claim is None:
        return
    event = inbound_event_payload_event(claim.event)
    if event is None:
        fail_inbound_event(
            claim, error_code="poison_payload", error="inbound event payload is missing or not an object"
        )
        return
    config = _slack_config_for_workspace(
        claim.event.provider_account_id,
        receipt_team_id=claim.event.team_id,
    )
    if not config:
        _retry_inbound_claim(claim, error_code="no_team", error="slack workspace is not connected")
        return
    team = config.team
    if not (team.conversations_settings or {}).get("slack_enabled"):
        complete_inbound_event(claim)
        return
    try:
        with inbound_claim_scope(claim):
            _handle_supporthog_event(event, team, claim.event.provider_account_id)
        complete_inbound_event(claim)
    except Exception as exc:
        logger.exception(
            "supporthog_event_handler_failed",
            event_type=event.get("type"),
            inbound_event_id=inbound_event_id,
            error=str(exc),
        )
        _retry_inbound_claim(claim, error_code="handler_failed", error=str(exc)[:INBOUND_ERROR_MAX_LENGTH])


@shared_task(
    name="products.conversations.backend.tasks.process_supporthog_event_receipt",
    ignore_result=True,
)
@skip_team_scope_audit
def process_supporthog_event_receipt(inbound_event_id: str) -> None:
    _process_event_from_receipt(inbound_event_id)


@shared_task(
    name="products.conversations.backend.tasks.process_supporthog_event",
    ignore_result=True,
    max_retries=3,
    default_retry_delay=5,
)
@skip_team_scope_audit
def process_supporthog_event(
    event: dict[str, Any] | None = None,
    slack_team_id: str = "",
    event_id: str | None = None,
) -> None:
    if not event:
        return
    if event_id and _is_duplicate_supporthog_event(event_id):
        logger.info("supporthog_event_duplicate_skipped", event_id=event_id)
        return

    config = _slack_config_for_workspace(slack_team_id)
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

    try:
        _handle_supporthog_event(event, team, slack_team_id)
    except Exception as e:
        logger.exception(
            "supporthog_event_handler_failed",
            event_type=event.get("type"),
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


def _slack_api_error_code(exc: Exception) -> str | None:
    if not isinstance(exc, SlackApiError) or exc.response is None:
        return None
    error = exc.response.get("error")
    return error if isinstance(error, str) else None


def _update_supporthog_prompt(team: Team, channel: str, message_ts: str, text: str) -> PromptUpdateResult:
    """Replace the "open a ticket?" prompt in place with a new status line (buttons removed).

    Never raises. Callers retry only a ``transient`` result. A missing or deleted prompt
    cannot recover, so those must not sit in the inbound retry queue.
    """
    if not channel or not message_ts:
        return "missing"
    try:
        get_slack_client(team).chat_update(
            channel=channel,
            ts=message_ts,
            text=text,
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
        )
        return "updated"
    except Exception as exc:
        logger.warning("supporthog_interactivity_prompt_update_failed", exc_info=True)
        error_code = _slack_api_error_code(exc)
        if error_code in _PERMANENT_PROMPT_UPDATE_ERROR_CODES:
            return "permanent"
        return "transient"


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


def _raise_if_retry_allowed(allow_retry: bool) -> None:
    if allow_retry:
        raise TransientInboundError


def _handle_supporthog_interactivity(
    payload: dict[str, Any],
    slack_team_id: str,
    *,
    is_retry: bool,
    allow_retry: bool,
    receipt_team_id: int | None = None,
) -> bool:
    """Handle a button click from the opt-in "open a ticket?" confirmation prompt."""
    config = _slack_config_for_workspace(slack_team_id, receipt_team_id=receipt_team_id)
    if not config:
        logger.warning("supporthog_interactivity_no_team", slack_team_id=slack_team_id)
        return receipt_team_id is None

    team = config.team
    support_settings = team.conversations_settings or {}
    if not support_settings.get("slack_enabled"):
        return True

    if payload.get("type") != "block_actions":
        return True

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
        # Echoed back from the prompt's button value, normalized at the trust boundary: the
        # value round-trips through Slack, and prompts posted before the verdict was stamped
        # in lack the key entirely — anything off-vocabulary becomes "unknown" so the funnel
        # property never carries junk. slack_user_id here is the clicker, not necessarily
        # the nudged author — buttons are clickable by anyone in the channel.
        raw_verdict = value.get("classifier")
        classifier_verdict: NudgeFunnelVerdict = (
            cast(NudgeFunnelVerdict, raw_verdict) if raw_verdict in get_args(NudgeClassifierVerdict) else "unknown"
        )
        click_properties = nudge_event_properties(source_channel, source_message_ts, clicker, classifier_verdict)

        if action_id == TICKET_CONFIRM_ACTION_DISMISS:
            _delete_supporthog_prompt(team, prompt_channel, prompt_ts)
            _post_dismiss_acknowledgment(team, prompt_channel, clicker, source_message_ts)
            # Don't pester them again in this channel for a while.
            if clicker:
                suppress_nudge(team.pk, prompt_channel, clicker, NUDGE_DISMISS_TTL)
            capture_nudge_event(team, "support nudge dismissed", click_properties)
            return True
        if action_id == TICKET_CONFIRM_ACTION_OPEN:
            ticket = None
            if source_channel and source_message_ts:
                # Ticket creation takes several seconds (Slack fetches + backfill) and the
                # click may have crossed a region on the way here — replace the buttons with
                # a progress line right away so the click visibly landed and repeat clicks
                # stop. First attempt only, and only while no sibling delivery has already
                # resolved the prompt (a stale placeholder must not overwrite a confirmation).
                ticket_already_open = Ticket.objects.filter(
                    team=team, slack_channel_id=source_channel, slack_thread_ts=source_message_ts
                ).exists()
                if not is_retry and not ticket_already_open:
                    _update_supporthog_prompt(
                        team, prompt_channel, prompt_ts, ":hourglass_flowing_sand: Opening a ticket…"
                    )
                try:
                    ticket = create_ticket_from_confirmation(
                        team=team,
                        slack_team_id=slack_team_id,
                        slack_channel_id=source_channel,
                        message_ts=source_message_ts,
                    )
                except SlackConfirmationNeedsRetry:
                    _raise_if_retry_allowed(allow_retry)
                except Exception as e:
                    logger.exception("supporthog_interactivity_create_failed", error=str(e))
                    # Retry transient failures. The retried run redoes the whole handler,
                    # so the prompt still resolves on eventual success. Once retries are
                    # exhausted, fall through to the error update below rather than leaving
                    # the user staring at live buttons forever.
                    _raise_if_retry_allowed(allow_retry)
            # Replace the prompt in place: a confirmation when we have a ticket (created or
            # already open), or an explicit error so a failed open never reads as success.
            # post_confirmation=False above means no separate confirmation was posted.
            if ticket:
                text = ticket_created_text(ticket)
            else:
                emoji = get_safe_ticket_emoji(support_settings)
                text = f":warning: Couldn't open a ticket — react with :{emoji}: or @mention us to try again."
            final_update = _update_supporthog_prompt(team, prompt_channel, prompt_ts, text)
            prompt_can_be_updated = bool(prompt_channel and prompt_ts)
            if final_update == "transient" and prompt_can_be_updated:
                # The progress placeholder must never be the prompt's last word. Retry a
                # transient Slack failure. A deleted or unauthorized prompt cannot recover.
                _raise_if_retry_allowed(allow_retry)
            # Captured after all retry exits (each retry re-raise leaves the task first),
            # so the event fires once with the final outcome.
            capture_nudge_event(
                team,
                "support nudge open ticket clicked",
                {
                    **click_properties,
                    "ticket_created": ticket is not None,
                    "ticket_id": str(ticket.id) if ticket else None,
                },
            )
            return ticket is not None
    return True


def _process_interactivity_from_receipt(inbound_event_id: str) -> None:
    claim = claim_inbound_event(inbound_event_id)
    if claim is None:
        return
    payload = claim.event.payload
    if not isinstance(payload, dict):
        fail_inbound_event(
            claim, error_code="poison_payload", error="inbound interactivity payload is missing or not an object"
        )
        return
    config = _slack_config_for_workspace(
        claim.event.provider_account_id,
        receipt_team_id=claim.event.team_id,
    )
    if not config:
        _retry_inbound_claim(claim, error_code="no_team", error="slack workspace is not connected")
        return
    try:
        with inbound_claim_scope(claim):
            resolved = _handle_supporthog_interactivity(
                payload,
                claim.event.provider_account_id,
                is_retry=claim.event.attempts > 1,
                allow_retry=claim.allow_retry,
                receipt_team_id=claim.event.team_id,
            )
        if resolved:
            complete_inbound_event(claim)
        else:
            fail_inbound_event(
                claim,
                error_code="interactivity_failed",
                error="Slack interactivity could not be completed",
            )
    except TransientInboundError:
        _retry_inbound_claim(claim, error_code="transient", error="interactivity work needs another attempt")
    except Exception as exc:
        logger.exception("supporthog_interactivity_handler_failed", inbound_event_id=inbound_event_id, error=str(exc))
        _retry_inbound_claim(claim, error_code="handler_failed", error=str(exc)[:INBOUND_ERROR_MAX_LENGTH])


@shared_task(
    name="products.conversations.backend.tasks.process_supporthog_interactivity_receipt",
    ignore_result=True,
)
@skip_team_scope_audit
def process_supporthog_interactivity_receipt(inbound_event_id: str) -> None:
    _process_interactivity_from_receipt(inbound_event_id)


@shared_task(
    name="products.conversations.backend.tasks.process_supporthog_interactivity",
    ignore_result=True,
    max_retries=3,
    default_retry_delay=5,
)
@skip_team_scope_audit
def process_supporthog_interactivity(
    payload: dict[str, Any] | None = None,
    slack_team_id: str = "",
) -> None:
    """Handle a button click from the opt-in "open a ticket?" confirmation prompt."""
    if not payload:
        return
    celery_retries = int(getattr(cast(Any, process_supporthog_interactivity).request, "retries", 0) or 0)
    try:
        _handle_supporthog_interactivity(
            payload,
            slack_team_id,
            is_retry=celery_retries > 0,
            allow_retry=True,
        )
    except TransientInboundError as exc:
        try:
            raise cast(Any, process_supporthog_interactivity).retry() from exc
        except MaxRetriesExceededError:
            _handle_supporthog_interactivity(payload, slack_team_id, is_retry=True, allow_retry=False)


@shared_task(
    name="products.conversations.backend.tasks.sweep_inbound_events",
    ignore_result=True,
)
@skip_team_scope_audit
def sweep_inbound_events() -> None:
    """Re-drive due Slack receipts and expire payloads. Celery is only a wake-up hint."""
    now = timezone.now()
    due_rows = due_inbound_event_ids(limit=INBOUND_SWEEP_BATCH_SIZE, now=now)
    dispatched = 0
    for inbound_event_id, source in due_rows:
        if wake_inbound_event(ConversationInboundEvent(id=inbound_event_id, source=source)):
            dispatched += 1

    payload_gc_count = drain_inbound_retention(cleanup_inbound_payloads, now)
    tombstone_delete_count = drain_inbound_retention(delete_inbound_tombstones, now)
    queue_metrics = record_inbound_queue_metrics(now)
    if dispatched or payload_gc_count or tombstone_delete_count:
        logger.info(
            "sweep_inbound_events_completed",
            dispatched=dispatched,
            payload_gc_count=payload_gc_count,
            tombstone_delete_count=tombstone_delete_count,
            pending_count=queue_metrics.pending_count,
            processing_count=queue_metrics.processing_count,
            oldest_ready_age_seconds=queue_metrics.oldest_ready_age_seconds,
        )


@shared_task(
    name="products.conversations.backend.tasks.post_reply_to_slack",
    ignore_result=True,
    max_retries=3,
    default_retry_delay=5,
)
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

    slack_text, slack_blocks = rich_content_to_slack_payload(
        rich_content, content, include_images=False, organization_id=team.organization_id
    )
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
                    missing_file_scopes=supporthog_missing_file_scopes(team),
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
