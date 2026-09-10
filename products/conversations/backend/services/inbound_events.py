from __future__ import annotations

import random
import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.ph_client import ph_scoped_capture

from products.conversations.backend.metrics import (
    INBOUND_ATTEMPTS_TOTAL,
    INBOUND_BACKLOG,
    INBOUND_LEASES_TOTAL,
    INBOUND_OLDEST_READY_AGE_SECONDS,
)
from products.conversations.backend.models import ConversationInboundEvent, ConversationInboundEventSource
from products.conversations.backend.models.inbound_event import (
    INBOUND_ERROR_MAX_LENGTH,
    INBOUND_PAYLOAD_TTL,
    INBOUND_TOMBSTONE_TTL,
    InboundPayloadTooLargeError,
    reject_oversized_inbound_payload,
)

logger = structlog.get_logger(__name__)

INBOUND_LEASE_SECONDS = 120
INBOUND_MAX_ATTEMPTS = 10
INBOUND_BACKOFF_BASE_SECONDS = 2
INBOUND_BACKOFF_MAX_SECONDS = 60
INBOUND_SWEEP_BATCH_SIZE = 100
# pinned: analytics event name — renaming breaks historical ClickHouse queries
INBOUND_SWEEP_EVENT = "conversations_inbound_sweep"


class TransientInboundError(Exception):
    """Work that should be retried from the Postgres receipt rather than Celery retry."""


@frozen
class InboundClaim:
    event: ConversationInboundEvent
    allow_retry: bool
    expired_reclaim: bool


def slack_retry_metadata(request: HttpRequest) -> tuple[int | None, str]:
    raw_num = request.headers.get("X-Slack-Retry-Num")
    reason = (request.headers.get("X-Slack-Retry-Reason") or "")[:64]
    if not raw_num:
        return None, reason
    try:
        retry_num = int(raw_num)
    except ValueError:
        return None, reason
    if retry_num < 0:
        return None, reason
    return retry_num, reason


def slack_events_source_id(*, event_id: str | None, signed_body: bytes) -> str:
    if event_id:
        return event_id[:512]
    return hashlib.sha256(signed_body).hexdigest()


def slack_interactivity_source_id(*, payload: dict[str, Any], signed_body: bytes) -> str:
    trigger_id = str(payload.get("trigger_id") or "")
    if not trigger_id:
        return hashlib.sha256(signed_body).hexdigest()
    actions = payload.get("actions") or []
    action = actions[0] if actions and isinstance(actions[0], dict) else {}
    action_id = str(action.get("action_id") or "")
    container = payload.get("container") if isinstance(payload.get("container"), dict) else {}
    container_key = ":".join(str(container.get(key) or "") for key in ("type", "message_ts", "channel_id", "thread_ts"))
    composed = f"{trigger_id}:{action_id}:{container_key}"
    if len(composed) <= 512:
        return composed
    return hashlib.sha256(composed.encode()).hexdigest()


def retry_delay_seconds(attempts: int) -> int:
    exponent = max(attempts - 1, 0)
    backoff = min(INBOUND_BACKOFF_BASE_SECONDS * (2 ** min(exponent, 8)), INBOUND_BACKOFF_MAX_SECONDS)
    jitter = random.uniform(0, backoff * 0.5)
    return max(int(backoff + jitter), 1)


def _safe_wake(wake: Callable[[ConversationInboundEvent], None], row: ConversationInboundEvent) -> None:
    try:
        wake(row)
    except Exception:
        logger.exception("inbound_event_dispatch_failed", inbound_event_id=str(row.id), source=row.source)


def _should_wake(row: ConversationInboundEvent, *, now: datetime) -> bool:
    if row.status == ConversationInboundEvent.Status.PENDING:
        return True
    return (
        row.status == ConversationInboundEvent.Status.PROCESSING
        and row.lease_expires_at is not None
        and row.lease_expires_at <= now
    )


def persist_inbound_event(
    *,
    team: Team,
    source: str,
    source_id: str,
    provider_account_id: str,
    payload: dict[str, Any] | None,
    provider_retry_num: int | None,
    provider_retry_reason: str,
) -> ConversationInboundEvent:
    status = ConversationInboundEvent.Status.PENDING
    error_code = ""
    error = ""
    terminal_at = None
    stored_payload: dict[str, Any] | None = payload
    try:
        reject_oversized_inbound_payload(payload)
    except InboundPayloadTooLargeError as exc:
        stored_payload = None
        status = ConversationInboundEvent.Status.FAILED
        error_code = "payload_too_large"
        error = str(exc)[:INBOUND_ERROR_MAX_LENGTH]
        terminal_at = timezone.now()

    defaults = {
        "provider_account_id": provider_account_id,
        "provider_retry_num": provider_retry_num,
        "provider_retry_reason": provider_retry_reason,
        "status": status,
        "payload": stored_payload,
        "last_error_code": error_code,
        "last_error": error,
        "terminal_at": terminal_at,
        "due_at": timezone.now(),
    }
    try:
        with transaction.atomic():
            return ConversationInboundEvent.objects.for_team(team.id).create(
                team=team,
                source=source,
                source_id=source_id,
                **defaults,
            )
    except IntegrityError:
        row = ConversationInboundEvent.objects.for_team(team.id).get(source=source, source_id=source_id)
        ConversationInboundEvent.objects.for_team(team.id).filter(id=row.id).update(
            provider_retry_num=provider_retry_num,
            provider_retry_reason=provider_retry_reason,
            updated_at=timezone.now(),
        )
        row.refresh_from_db()
        return row


def accept_inbound_event(
    *,
    team: Team,
    source: str,
    source_id: str,
    provider_account_id: str,
    payload: dict[str, Any] | None,
    provider_retry_num: int | None,
    provider_retry_reason: str,
    wake: Callable[[ConversationInboundEvent], None],
) -> ConversationInboundEvent:
    now = timezone.now()
    with transaction.atomic():
        row = persist_inbound_event(
            team=team,
            source=source,
            source_id=source_id,
            provider_account_id=provider_account_id,
            payload=payload,
            provider_retry_num=provider_retry_num,
            provider_retry_reason=provider_retry_reason,
        )
        if _should_wake(row, now=now):
            transaction.on_commit(lambda: _safe_wake(wake, row))
    return row


def claim_inbound_event(inbound_event_id: str) -> InboundClaim | None:
    now = timezone.now()
    lease_until = now + timedelta(seconds=INBOUND_LEASE_SECONDS)
    with transaction.atomic():
        row = (
            ConversationInboundEvent.objects.unscoped()
            .select_for_update(skip_locked=True)
            .filter(id=inbound_event_id)
            .filter(
                Q(status=ConversationInboundEvent.Status.PENDING, due_at__lte=now)
                | Q(status=ConversationInboundEvent.Status.PROCESSING, lease_expires_at__lte=now)
            )
            .first()
        )
        if row is None:
            INBOUND_LEASES_TOTAL.labels(result="busy").inc()
            return None
        expired_reclaim = row.status == ConversationInboundEvent.Status.PROCESSING
        row.status = ConversationInboundEvent.Status.PROCESSING
        row.lease_expires_at = lease_until
        row.fencing_token += 1
        row.attempts += 1
        row.save(update_fields=["status", "lease_expires_at", "fencing_token", "attempts", "updated_at"])
    INBOUND_LEASES_TOTAL.labels(result="expired_reclaim" if expired_reclaim else "claimed").inc()
    INBOUND_ATTEMPTS_TOTAL.labels(source=row.source, result="claimed").inc()
    return InboundClaim(
        event=row,
        allow_retry=row.attempts < INBOUND_MAX_ATTEMPTS,
        expired_reclaim=expired_reclaim,
    )


def _fenced(claim: InboundClaim) -> Any:
    return ConversationInboundEvent.objects.unscoped().filter(
        id=claim.event.id,
        fencing_token=claim.event.fencing_token,
    )


def complete_inbound_event(claim: InboundClaim, *, error_code: str = "", error: str = "") -> bool:
    now = timezone.now()
    updated = _fenced(claim).update(
        status=ConversationInboundEvent.Status.PROCESSED,
        terminal_at=now,
        lease_expires_at=None,
        last_error_code=error_code,
        last_error=error[:INBOUND_ERROR_MAX_LENGTH],
        updated_at=now,
    )
    if updated:
        INBOUND_ATTEMPTS_TOTAL.labels(source=claim.event.source, result="processed").inc()
    return updated == 1


def fail_inbound_event(claim: InboundClaim, *, error_code: str, error: str) -> bool:
    now = timezone.now()
    updated = _fenced(claim).update(
        status=ConversationInboundEvent.Status.FAILED,
        terminal_at=now,
        lease_expires_at=None,
        last_error_code=error_code,
        last_error=error[:INBOUND_ERROR_MAX_LENGTH],
        updated_at=now,
    )
    if updated:
        INBOUND_ATTEMPTS_TOTAL.labels(source=claim.event.source, result="failed").inc()
    return updated == 1


def schedule_inbound_retry(claim: InboundClaim, *, error_code: str, error: str) -> int | None:
    delay = retry_delay_seconds(claim.event.attempts)
    now = timezone.now()
    updated = _fenced(claim).update(
        status=ConversationInboundEvent.Status.PENDING,
        due_at=now + timedelta(seconds=delay),
        lease_expires_at=None,
        last_error_code=error_code,
        last_error=error[:INBOUND_ERROR_MAX_LENGTH],
        updated_at=now,
    )
    if not updated:
        return None
    INBOUND_ATTEMPTS_TOTAL.labels(source=claim.event.source, result="retry").inc()
    return delay


def due_inbound_event_ids(*, limit: int, now: datetime) -> list[tuple[UUID, str]]:
    return list(
        ConversationInboundEvent.objects.unscoped()
        .filter(
            Q(status=ConversationInboundEvent.Status.PENDING, due_at__lte=now)
            | Q(status=ConversationInboundEvent.Status.PROCESSING, lease_expires_at__lte=now)
        )
        .order_by("due_at")
        .values_list("id", "source")[:limit]
    )


def cleanup_inbound_payloads(now: datetime) -> int:
    cutoff = now - INBOUND_PAYLOAD_TTL
    return (
        ConversationInboundEvent.objects.unscoped()
        .filter(
            status__in=ConversationInboundEvent.TERMINAL_STATUSES,
            payload__isnull=False,
            terminal_at__lte=cutoff,
        )
        .update(payload=None, updated_at=now)
    )


def delete_inbound_tombstones(now: datetime) -> int:
    cutoff = now - INBOUND_TOMBSTONE_TTL
    deleted, _ = (
        ConversationInboundEvent.objects.unscoped()
        .filter(
            status__in=ConversationInboundEvent.TERMINAL_STATUSES,
            terminal_at__lte=cutoff,
        )
        .delete()
    )
    return deleted


def record_inbound_queue_metrics(now: datetime) -> float:
    oldest_age = 0.0
    for source in ConversationInboundEventSource.values:
        for status in (ConversationInboundEvent.Status.PENDING, ConversationInboundEvent.Status.PROCESSING):
            count = ConversationInboundEvent.objects.unscoped().filter(source=source, status=status).count()
            INBOUND_BACKLOG.labels(status=status, source=source).set(count)
    oldest = (
        ConversationInboundEvent.objects.unscoped()
        .filter(
            Q(status=ConversationInboundEvent.Status.PENDING, due_at__lte=now)
            | Q(status=ConversationInboundEvent.Status.PROCESSING, lease_expires_at__lte=now)
        )
        .order_by("due_at")
        .values_list("due_at", flat=True)
        .first()
    )
    if oldest is not None:
        oldest_age = max((now - oldest).total_seconds(), 0.0)
    INBOUND_OLDEST_READY_AGE_SECONDS.set(oldest_age)
    return oldest_age


def emit_inbound_sweep_event(
    *,
    pending_count: int,
    processing_count: int,
    dispatched_count: int,
    payload_gc_count: int,
    tombstone_delete_count: int,
    oldest_ready_age_seconds: float,
) -> None:
    with ph_scoped_capture() as capture:
        capture(
            distinct_id="conversations-inbound-sweeper",
            event=INBOUND_SWEEP_EVENT,
            properties={
                "pending_count": pending_count,
                "processing_count": processing_count,
                "dispatched_count": dispatched_count,
                "payload_gc_count": payload_gc_count,
                "tombstone_delete_count": tombstone_delete_count,
                "oldest_ready_age_seconds": oldest_ready_age_seconds,
            },
        )


def inbound_event_payload_event(row: ConversationInboundEvent) -> dict[str, Any] | None:
    payload = row.payload
    if not isinstance(payload, dict):
        return None
    inner = payload.get("event")
    if isinstance(inner, dict):
        return inner
    return None
