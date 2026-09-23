"""Slack inbound events, interactivity, and outbound replies."""

import json
from typing import Any, Literal, NoReturn, cast, get_args
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
from posthog.dataclasses import frozen
from posthog.helpers.slack_identity import (
    resolve_posthog_user_for_slack,
    resolve_slack_avatar_by_email,
    resolve_slack_user,
)
from posthog.models.team import Team
from posthog.models.uploaded_media import UploadedMedia
from posthog.scoping_audit import skip_team_scope_audit
from posthog.storage import object_storage

from products.conversations.backend.cache import NUDGE_DISMISS_TTL, suppress_nudge
from products.conversations.backend.models import (
    ConversationDeliveryPart,
    ConversationInboundEvent,
    ConversationInboundEventSource,
    TeamConversationsSlackConfig,
)
from products.conversations.backend.models.delivery import DELIVERY_ERROR_MAX_LENGTH
from products.conversations.backend.models.inbound_event import INBOUND_ERROR_MAX_LENGTH
from products.conversations.backend.models.ticket import Ticket
from products.conversations.backend.services.attachments import CONVERSATIONS_MAX_IMAGE_BYTES
from products.conversations.backend.services.delivery import (
    DELIVERY_PART_KEY_BODY,
    DELIVERY_PART_KEY_FALLBACK,
    DELIVERY_SWEEP_BATCH_SIZE,
    IMAGE_UPLOAD_STEP_BYTES,
    IMAGE_UPLOAD_STEP_COMPLETE,
    IMAGE_UPLOAD_STEP_GET,
    DeliveryClaim,
    PermanentDeliveryError,
    TransientDeliveryError,
    accept_delivery_part,
    claim_delivery_part,
    cleanup_delivery_snapshots,
    complete_slack_body_delivery,
    defer_delivery_part,
    drain_delivery_retention,
    due_delivery_part_ids,
    fail_delivery_part,
    is_slack_image_part_key,
    maybe_enqueue_slack_fallback,
    persist_delivery_part_payload,
    pin_slack_fallback_payload,
    record_delivery_queue_metrics,
    schedule_delivery_retry,
    slack_fallback_payload,
)
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
    TICKET_VIEW_ACTION,
    NudgeClassifierVerdict,
    NudgeFunnelVerdict,
    SlackConfirmationNeedsRetry,
    capture_nudge_event,
    capture_support_event,
    create_ticket_from_confirmation,
    get_bot_user_id,
    get_safe_ticket_emoji,
    get_slack_client,
    handle_link_shared,
    handle_member_joined_channel,
    handle_member_left_channel,
    handle_support_mention,
    handle_support_message,
    handle_support_reaction,
    my_tickets_link,
    nudge_event_properties,
    ticket_created_blocks,
    ticket_created_text,
    ticket_deep_link,
)

from ..support_slack import SUPPORT_SLACK_ALLOWED_HOST_SUFFIXES, supporthog_missing_file_scopes

logger = structlog.get_logger(__name__)
SUPPORTHOG_EVENT_IDEMPOTENCY_TTL_SECONDS = 6 * 60
SUPPORTHOG_EVENT_IDEMPOTENCY_KEY_PREFIX = "supporthog:slack:event:"
# How long the fallback waits when a redrive puts an image back in flight.
SLACK_FALLBACK_WAIT_SECONDS = 30
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
_PERMANENT_CHAT_POST_ERROR_CODES = frozenset(
    {
        "account_inactive",
        "cannot_reply_to_message",
        "channel_is_frozen",
        "channel_not_found",
        "ekm_access_denied",
        "invalid_auth",
        "invalid_blocks",
        "invalid_blocks_format",
        "is_archived",
        "missing_scope",
        "msg_too_long",
        "not_authed",
        "not_in_channel",
        "restricted_action",
        "team_access_not_granted",
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
    elif event_type == "link_shared":
        handle_link_shared(event, team, slack_team_id)
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


def _update_supporthog_prompt(
    team: Team, channel: str, message_ts: str, text: str, *, blocks: list[dict] | None = None
) -> PromptUpdateResult:
    """Replace the "open a ticket?" prompt in place with a new status line.

    The prompt's own buttons go away unless the caller passes replacement ``blocks`` — a
    resolved prompt carries the confirmation's "View ticket" button, nothing else.

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
            blocks=blocks or [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
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


def _post_ticket_link(
    team: Team,
    *,
    slack_team_id: str,
    channel: str,
    thread_ts: str,
    clicker: str,
    ticket_number: int | str | None,
) -> None:
    """Answer a "View ticket" click with an ephemeral link, so only the clicker sees the URL.

    The button rides on a public confirmation, so anyone in the channel can click it, and both
    kinds of clicker get somewhere useful: a member of the team's organization gets the ticket
    in Support, and everyone else gets their own ticket list. Nobody is told the other view
    exists. Two checks decide which: the clicker belongs to the workspace the app is installed
    in, and their Slack profile email matches an organization member. The workspace check is
    what makes the email check worth anything — an external (Slack Connect) participant's
    profile email is set by their own workspace, so it can claim a teammate's address.

    Best-effort: a failure leaves the click unanswered rather than retrying.
    """
    if not channel or not clicker:
        return
    try:
        number = int(ticket_number) if ticket_number is not None else 0
    except (TypeError, ValueError):
        number = 0
    try:
        client = get_slack_client(team)
        ticket = Ticket.objects.filter(team=team, ticket_number=number).first() if number > 0 else None
        is_org_member = False
        if ticket is None:
            logger.warning("supporthog_ticket_link_unknown_ticket", team_id=team.pk, ticket_number=number)
            text = "That ticket isn't available any more."
        else:
            slack_user = resolve_slack_user(client, clicker, workspace=slack_team_id)
            in_workspace = bool(slack_team_id) and slack_user.get("team_id") == slack_team_id
            is_org_member = in_workspace and resolve_posthog_user_for_slack(slack_user.get("email"), team) is not None
            if is_org_member:
                link = ticket_deep_link(ticket, team)
                text = f"<{link}|Ticket #{ticket.ticket_number}>. Only you can see this message."
            else:
                # Not "no access". The clicker is usually the requester, whose own list carries
                # this ticket, but a bystander in the channel gets the same answer and only sees
                # their own list, so the copy stays true either way. Replying always works.
                text = (
                    f"Ticket #{ticket.ticket_number} is with our support team. "
                    f"If you raised it, follow it in <{my_tickets_link(ticket)}|your PostHog tickets>, "
                    "or just reply in this thread."
                )
        client.chat_postEphemeral(channel=channel, user=clicker, thread_ts=thread_ts or None, text=text)
        capture_support_event(
            team,
            "support slack ticket link clicked",
            {
                "slack_team_id": slack_team_id,
                "slack_channel_id": channel,
                "ticket_found": ticket is not None,
                "is_org_member": is_org_member,
            },
        )
    except Exception:
        logger.warning("supporthog_ticket_link_failed", exc_info=True)


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

        if action_id == TICKET_VIEW_ACTION:
            _post_ticket_link(
                team,
                slack_team_id=slack_team_id,
                channel=prompt_channel,
                thread_ts=(payload.get("message") or {}).get("thread_ts") or "",
                clicker=clicker,
                ticket_number=value.get("ticket_number"),
            )
            return True

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
            final_update = _update_supporthog_prompt(
                team,
                prompt_channel,
                prompt_ts,
                text,
                blocks=ticket_created_blocks(ticket) if ticket else None,
            )
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


def wake_delivery_part(row: ConversationDeliveryPart, *, countdown: int | None = None) -> bool:
    kwargs = {"delivery_part_id": str(row.id)}
    try:
        # retry=False: the part is already committed, so a hung broker must not
        # stall the comment request. The minute sweeper re-drives pending rows.
        apply_kwargs: dict[str, Any] = {"kwargs": kwargs, "retry": False}
        if countdown is not None:
            apply_kwargs["countdown"] = countdown
        cast(Any, process_slack_delivery_part).apply_async(**apply_kwargs)
    except Exception:
        logger.exception("delivery_part_redrive_failed", delivery_part_id=str(row.id), part_key=row.part_key)
        return False
    return True


def _wake_fallback_if_ready(part: ConversationDeliveryPart) -> None:
    fallback = maybe_enqueue_slack_fallback(part)
    if fallback is not None:
        wake_delivery_part(fallback)


def _fail_claimed_delivery_part(claim: DeliveryClaim, *, error_code: str, error: str) -> bool:
    if not fail_delivery_part(claim, error_code=error_code, error=error):
        return False
    _wake_fallback_if_ready(claim.part)
    return True


def _retry_delivery_claim(
    claim: DeliveryClaim,
    *,
    error_code: str,
    error: str,
    retry_after_seconds: int | None = None,
) -> None:
    if not claim.allow_retry:
        _fail_claimed_delivery_part(claim, error_code=error_code, error=error)
        return
    delay = schedule_delivery_retry(
        claim,
        error_code=error_code,
        error=error,
        retry_after_seconds=retry_after_seconds,
    )
    if delay is not None:
        wake_delivery_part(claim.part, countdown=delay)


def _retry_after_seconds(exc: Exception) -> int | None:
    if not isinstance(exc, SlackApiError) or exc.response is None:
        return None
    headers = getattr(exc.response, "headers", None) or {}
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        return None
    try:
        return int(float(str(raw)))
    except (TypeError, ValueError):
        return None


def _is_timeout_or_disconnect(exc: Exception) -> bool:
    return isinstance(
        exc,
        (
            TimeoutError,
            ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        ),
    )


def _slack_response_ts(response: Any) -> str:
    if response is None:
        return ""
    getter = getattr(response, "get", None)
    if not callable(getter):
        return ""
    ts = getter("ts")
    if isinstance(ts, str) and ts:
        return ts
    message = getter("message")
    if isinstance(message, dict):
        nested = message.get("ts")
        if isinstance(nested, str) and nested:
            return nested
    return ""


class ExpiredSlackUploadURLError(TransientDeliveryError):
    """The Slack upload URL is gone, so the next attempt must start at get-upload."""


def _raise_slack_body_error(exc: Exception) -> NoReturn:
    error_code = _slack_api_error_code(exc) or ""
    retry_after = _retry_after_seconds(exc)
    if error_code in _PERMANENT_CHAT_POST_ERROR_CODES:
        raise PermanentDeliveryError(str(exc), error_code=error_code) from exc
    raise TransientDeliveryError(str(exc), retry_after_seconds=retry_after) from exc


def _transient_error_code(exc: TransientDeliveryError) -> str:
    cause = exc.__cause__
    if isinstance(cause, Exception):
        code = _slack_api_error_code(cause)
        if code:
            return code[:64]
        if _is_timeout_or_disconnect(cause):
            return "timeout"
        status = getattr(getattr(cause, "response", None), "status_code", None)
        if status == 429:
            return "ratelimited"
        if isinstance(status, int) and status >= 500:
            return "http_5xx"
    return "transient"


@frozen
class SlackSender:
    username: str
    icon_url: str | None


def _slack_sender(*, client: Any, team: Team, payload: dict[str, Any], ticket_id: str = "") -> SlackSender:
    support_settings = team.conversations_settings or {}
    author_name = str(payload.get("author_name") or "")
    author_email = str(payload.get("author_email") or "")
    author_icon_url: str | None = None
    if author_email:
        try:
            author_icon_url = resolve_slack_avatar_by_email(client, author_email)
        except Exception:
            logger.warning("slack_delivery_avatar_lookup_failed", ticket_id=ticket_id, exc_info=True)
    return SlackSender(
        username=author_name or support_settings.get("slack_bot_display_name") or "Support",
        icon_url=author_icon_url or support_settings.get("slack_bot_icon_url"),
    )


def _post_slack_body(
    *,
    client: Any,
    team: Team,
    payload: dict[str, Any],
    route: dict[str, Any],
    client_msg_id: str,
) -> str:
    slack_text = str(payload.get("text") or "")
    slack_blocks = payload.get("blocks")
    if not isinstance(slack_blocks, list):
        slack_blocks = []
    if not slack_text.strip() and not slack_blocks:
        return ""

    sender = _slack_sender(client=client, team=team, payload=payload)
    message_kwargs: dict[str, Any] = {
        "channel": str(route.get("channel") or ""),
        "thread_ts": str(route.get("thread_ts") or ""),
        "text": slack_text,
        "username": sender.username,
    }
    if client_msg_id:
        message_kwargs["client_msg_id"] = client_msg_id
    if sender.icon_url:
        message_kwargs["icon_url"] = sender.icon_url
    if slack_blocks:
        message_kwargs["blocks"] = slack_blocks

    try:
        response = client.chat_postMessage(**message_kwargs)
    except SlackApiError as exc:
        # Slack may return the original ts on a duplicate-shaped error after a lost ACK.
        duplicate_ts = _slack_response_ts(exc.response)
        if duplicate_ts:
            return duplicate_ts
        _raise_slack_body_error(exc)
    except Exception as exc:
        _raise_slack_body_error(exc)
    ts = _slack_response_ts(response)
    if not ts:
        # Slack may have accepted the post. Retry with the same client_msg_id.
        raise TransientDeliveryError("Slack accepted the body without returning a timestamp")
    return ts


@frozen
class SlackDeliveryRuntime:
    client: Any
    team: Team
    payload: dict[str, Any]
    route: dict[str, Any]


def _reset_image_upload_step(claim: DeliveryClaim) -> bool:
    payload = claim.part.payload if isinstance(claim.part.payload, dict) else {}
    next_payload = {key: value for key, value in payload.items() if key not in {"file_id", "upload_url", "length"}}
    next_payload["step"] = IMAGE_UPLOAD_STEP_GET
    return persist_delivery_part_payload(claim, next_payload)


def _load_slack_delivery_runtime(claim: DeliveryClaim) -> SlackDeliveryRuntime | None:
    part = claim.part
    payload = part.payload if isinstance(part.payload, dict) else None
    route = part.route if isinstance(part.route, dict) else None
    if payload is None or route is None:
        _fail_claimed_delivery_part(
            claim,
            error_code="poison_payload",
            error="delivery part snapshot is missing or not an object",
        )
        return None
    channel = str(route.get("channel") or "")
    thread_ts = str(route.get("thread_ts") or "")
    if not channel or not thread_ts:
        _fail_claimed_delivery_part(
            claim,
            error_code="poison_route",
            error="delivery part route is missing channel or thread_ts",
        )
        return None
    delivery = part.delivery
    config = _slack_config_for_workspace(
        delivery.provider_account_id,
        receipt_team_id=delivery.team_id,
    )
    if not config:
        _retry_delivery_claim(claim, error_code="no_team", error="slack workspace is not connected")
        return None
    team = config.team
    if not (team.conversations_settings or {}).get("slack_enabled"):
        _fail_claimed_delivery_part(claim, error_code="slack_disabled", error="Slack replies are disabled")
        return None
    try:
        client = get_slack_client(team)
    except ValueError:
        _fail_claimed_delivery_part(
            claim, error_code="no_credentials", error="Support Slack bot token is not configured"
        )
        return None
    return SlackDeliveryRuntime(client=client, team=team, payload=payload, route=route)


def _deliver_slack_body(claim: DeliveryClaim, runtime: SlackDeliveryRuntime) -> None:
    ts = _post_slack_body(
        client=runtime.client,
        team=runtime.team,
        payload=runtime.payload,
        route=runtime.route,
        client_msg_id=claim.part.client_msg_id,
    )
    if not ts:
        logger.info("slack_delivery_body_empty", delivery_part_id=str(claim.part.id))
    for part in complete_slack_body_delivery(claim, provider_message_id=ts):
        wake_delivery_part(part)


def _deliver_slack_fallback(claim: DeliveryClaim, runtime: SlackDeliveryRuntime) -> None:
    snapshot = pin_slack_fallback_payload(claim)
    if snapshot is None:
        # A redrive put an image back in flight. Waiting is not a failed
        # attempt, so re-arm without spending the retry budget.
        defer_delivery_part(claim, seconds=SLACK_FALLBACK_WAIT_SECONDS, reason="images_in_flight")
        return
    if not snapshot.urls:
        accept_delivery_part(claim, provider_message_id="")
        return
    payload = {**runtime.payload, **slack_fallback_payload(snapshot)}
    ts = _post_slack_body(
        client=runtime.client,
        team=runtime.team,
        payload=payload,
        route=runtime.route,
        client_msg_id=claim.part.client_msg_id,
    )
    accept_delivery_part(claim, provider_message_id=ts)


def _image_step(payload: dict[str, Any]) -> str:
    step = payload.get("step")
    if step in {IMAGE_UPLOAD_STEP_GET, IMAGE_UPLOAD_STEP_BYTES, IMAGE_UPLOAD_STEP_COMPLETE}:
        return str(step)
    return IMAGE_UPLOAD_STEP_GET


def _deliver_slack_image(claim: DeliveryClaim, runtime: SlackDeliveryRuntime) -> None:
    payload = dict(runtime.payload)
    route = runtime.route
    step = _image_step(payload)
    image_url = payload.get("url")
    image_url = image_url if isinstance(image_url, str) else ""
    image_alt = payload.get("alt")
    image_alt = image_alt if isinstance(image_alt, str) else None
    media_team_id = payload.get("media_team_id")
    media_team_id = media_team_id if isinstance(media_team_id, int) else runtime.team.id
    image_name = _filename_for_slack_image(image_alt, image_url)
    slack_channel_id = str(route.get("channel") or "")
    slack_thread_ts = str(route.get("thread_ts") or "")

    if step == IMAGE_UPLOAD_STEP_BYTES and (not payload.get("upload_url") or not payload.get("file_id")):
        step = IMAGE_UPLOAD_STEP_GET
    if step == IMAGE_UPLOAD_STEP_COMPLETE and not payload.get("file_id"):
        step = IMAGE_UPLOAD_STEP_GET

    image_bytes: bytes | None = None
    if step in {IMAGE_UPLOAD_STEP_GET, IMAGE_UPLOAD_STEP_BYTES}:
        image_bytes = _read_image_bytes_for_slack_upload(media_team_id, image_url)
        if image_bytes is None:
            raise PermanentDeliveryError("Image bytes are not readable for Slack upload", error_code="image_unreadable")

    if step == IMAGE_UPLOAD_STEP_GET:
        if image_bytes is None:
            raise PermanentDeliveryError("Image bytes are not readable for Slack upload", error_code="image_unreadable")
        target = _slack_get_upload_url_external(runtime.client, filename=image_name, length=len(image_bytes))
        payload = {
            **payload,
            "step": IMAGE_UPLOAD_STEP_BYTES,
            "file_id": target.file_id,
            "upload_url": target.upload_url,
            "length": len(image_bytes),
        }
        if not persist_delivery_part_payload(claim, payload):
            return
        step = IMAGE_UPLOAD_STEP_BYTES

    if step == IMAGE_UPLOAD_STEP_BYTES:
        if image_bytes is None:
            raise PermanentDeliveryError("Image bytes are not readable for Slack upload", error_code="image_unreadable")
        upload_url = str(payload.get("upload_url") or "")
        if not _is_allowed_slack_upload_url(upload_url):
            raise PermanentDeliveryError("Slack returned a disallowed upload URL", error_code="disallowed_upload_url")
        _slack_post_upload_bytes(upload_url, image_bytes)
        payload = {**payload, "step": IMAGE_UPLOAD_STEP_COMPLETE}
        payload.pop("upload_url", None)
        if not persist_delivery_part_payload(claim, payload):
            return

    file_id = str(payload.get("file_id") or "")
    _slack_complete_upload_external(
        runtime.client,
        file_id=file_id,
        image_name=image_name,
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
    )
    if accept_delivery_part(claim, provider_message_id=file_id):
        _wake_fallback_if_ready(claim.part)


def _process_slack_delivery_part(delivery_part_id: str) -> None:
    claim = claim_delivery_part(delivery_part_id)
    if claim is None:
        return
    part = claim.part
    if (
        part.part_key != DELIVERY_PART_KEY_BODY
        and part.part_key != DELIVERY_PART_KEY_FALLBACK
        and not is_slack_image_part_key(part.part_key)
    ):
        _fail_claimed_delivery_part(
            claim,
            error_code="unsupported_part",
            error=f"Slack worker cannot process part_key={part.part_key}",
        )
        return
    runtime = _load_slack_delivery_runtime(claim)
    if runtime is None:
        return
    try:
        if part.part_key == DELIVERY_PART_KEY_BODY:
            _deliver_slack_body(claim, runtime)
            return
        if part.part_key == DELIVERY_PART_KEY_FALLBACK:
            _deliver_slack_fallback(claim, runtime)
            return
        _deliver_slack_image(claim, runtime)
    except ExpiredSlackUploadURLError as exc:
        if not _reset_image_upload_step(claim):
            return
        _retry_delivery_claim(
            claim,
            error_code="upload_url_expired",
            error=str(exc)[:DELIVERY_ERROR_MAX_LENGTH],
            retry_after_seconds=exc.retry_after_seconds,
        )
    except PermanentDeliveryError as exc:
        _fail_claimed_delivery_part(claim, error_code=exc.error_code, error=str(exc))
    except TransientDeliveryError as exc:
        _retry_delivery_claim(
            claim,
            error_code=_transient_error_code(exc),
            error=str(exc)[:DELIVERY_ERROR_MAX_LENGTH],
            retry_after_seconds=exc.retry_after_seconds,
        )
    except Exception as exc:
        logger.exception("slack_delivery_handler_failed", delivery_part_id=delivery_part_id, error=str(exc))
        _retry_delivery_claim(claim, error_code="handler_failed", error=str(exc)[:DELIVERY_ERROR_MAX_LENGTH])


@shared_task(
    name="products.conversations.backend.tasks.process_slack_delivery_part",
    ignore_result=True,
)
@skip_team_scope_audit
def process_slack_delivery_part(delivery_part_id: str) -> None:
    _process_slack_delivery_part(delivery_part_id)


@shared_task(
    name="products.conversations.backend.tasks.sweep_delivery_parts",
    ignore_result=True,
)
@skip_team_scope_audit
def sweep_delivery_parts() -> None:
    """Re-drive due Slack delivery parts. Celery is only a wake-up hint."""
    now = timezone.now()
    due_ids = due_delivery_part_ids(limit=DELIVERY_SWEEP_BATCH_SIZE, now=now)
    dispatched = 0
    for part_id in due_ids:
        if wake_delivery_part(ConversationDeliveryPart(id=part_id)):
            dispatched += 1

    snapshot_gc_count = drain_delivery_retention(cleanup_delivery_snapshots, now)
    queue_metrics = record_delivery_queue_metrics(now)
    if dispatched or snapshot_gc_count:
        logger.info(
            "sweep_delivery_parts_completed",
            dispatched=dispatched,
            snapshot_gc_count=snapshot_gc_count,
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


@frozen
class SlackUploadTarget:
    file_id: str
    upload_url: str


def _slack_get_upload_url_external(client: Any, *, filename: str, length: int) -> SlackUploadTarget:
    try:
        get_upload_url = client.api_call(
            api_method="files.getUploadURLExternal",
            params={
                "filename": filename,
                "length": length,
            },
        )
    except Exception as exc:
        _raise_slack_body_error(exc)
    if not get_upload_url.get("ok"):
        error = str(get_upload_url.get("error") or "get_upload_failed")
        message = f"files.getUploadURLExternal failed: {error}"
        if error in _PERMANENT_CHAT_POST_ERROR_CODES:
            raise PermanentDeliveryError(message, error_code=error)
        raise TransientDeliveryError(message)
    upload_url = get_upload_url.get("upload_url")
    file_id = get_upload_url.get("file_id")
    if not isinstance(upload_url, str) or not upload_url or not isinstance(file_id, str) or not file_id:
        raise TransientDeliveryError("files.getUploadURLExternal missing upload_url/file_id")
    if not _is_allowed_slack_upload_url(upload_url):
        raise PermanentDeliveryError(
            "files.getUploadURLExternal returned disallowed upload URL",
            error_code="disallowed_upload_url",
        )
    return SlackUploadTarget(file_id=file_id, upload_url=upload_url)


def _slack_post_upload_bytes(upload_url: str, image_bytes: bytes) -> None:
    try:
        upload_response = requests.post(
            upload_url,
            data=image_bytes,
            headers={"Content-Type": "application/octet-stream"},
            timeout=10,
        )
    except Exception as exc:
        _raise_slack_body_error(exc)
    if upload_response.status_code in (404, 410):
        raise ExpiredSlackUploadURLError("Slack upload URL expired")
    try:
        upload_response.raise_for_status()
    except Exception as exc:
        _raise_slack_body_error(exc)


def _slack_complete_upload_external(
    client: Any,
    *,
    file_id: str,
    image_name: str,
    slack_channel_id: str,
    slack_thread_ts: str,
) -> None:
    try:
        complete_upload = client.api_call(
            api_method="files.completeUploadExternal",
            json={
                "files": [{"id": file_id, "title": image_name}],
                "channel_id": slack_channel_id,
                "thread_ts": slack_thread_ts,
            },
        )
    except SlackApiError as exc:
        error_code = _slack_api_error_code(exc) or ""
        if error_code in {"file_not_found", "not_found"}:
            raise ExpiredSlackUploadURLError(str(exc)) from exc
        _raise_slack_body_error(exc)
    except Exception as exc:
        _raise_slack_body_error(exc)
    if not complete_upload.get("ok"):
        error = str(complete_upload.get("error") or "complete_upload_failed")
        message = f"files.completeUploadExternal failed: {error}"
        if error in {"file_not_found", "not_found"}:
            raise ExpiredSlackUploadURLError(message)
        if error in _PERMANENT_CHAT_POST_ERROR_CODES:
            raise PermanentDeliveryError(message, error_code=error)
        raise TransientDeliveryError(message)


def _upload_image_to_slack_thread(
    *,
    client,
    slack_channel_id: str,
    slack_thread_ts: str,
    image_name: str,
    image_bytes: bytes,
) -> None:
    # Slack deprecated files.upload; use external upload API flow.
    target = _slack_get_upload_url_external(client, filename=image_name, length=len(image_bytes))
    _slack_post_upload_bytes(target.upload_url, image_bytes)
    _slack_complete_upload_external(
        client,
        file_id=target.file_id,
        image_name=image_name,
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
    )


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
