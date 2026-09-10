from __future__ import annotations

import random
import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.utils import timezone

import structlog
from prometheus_client import Gauge

from posthog.dataclasses import frozen
from posthog.metrics import pushed_metrics_registry
from posthog.models.team import Team

from products.conversations.backend.metrics import INBOUND_ATTEMPTS_TOTAL, INBOUND_LEASES_TOTAL
from products.conversations.backend.models import ConversationInboundEvent, ConversationInboundEventSource
from products.conversations.backend.models.inbound_event import (
    INBOUND_ERROR_MAX_LENGTH,
    INBOUND_PAYLOAD_TTL,
    INBOUND_TOMBSTONE_TTL,
    InboundPayloadTooLargeError,
    reject_oversized_inbound_payload,
)

logger = structlog.get_logger(__name__)

# Covers a crashed worker. Live Slack create+backfill has no Celery time_limit, so this
# is reclaim latency, not a handler wall-clock.
INBOUND_LEASE_SECONDS = 20 * 60
INBOUND_MAX_ATTEMPTS = 20
INBOUND_BACKOFF_BASE_SECONDS = 15
INBOUND_BACKOFF_MAX_SECONDS = 15 * 60
INBOUND_MAX_AGE = INBOUND_PAYLOAD_TTL
INBOUND_SWEEP_BATCH_SIZE = 100
# Caps one Beat tick so retention catch-up cannot run unbounded.
INBOUND_SWEEP_MAX_ROUNDS = 20

InboundWake = Callable[[ConversationInboundEvent], object]


class TransientInboundError(Exception):
    """Work that should be retried from the Postgres receipt rather than Celery retry."""


@frozen
class InboundClaim:
    event: ConversationInboundEvent
    allow_retry: bool
    expired_reclaim: bool


@frozen
class InboundQueueMetrics:
    pending_count: int
    processing_count: int
    oldest_ready_age_seconds: float


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
    raw_action = actions[0] if actions else None
    action: dict[str, Any] = raw_action if isinstance(raw_action, dict) else {}
    action_id = str(action.get("action_id") or "")
    raw_container = payload.get("container")
    container: dict[str, Any] = raw_container if isinstance(raw_container, dict) else {}
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


def _safe_wake(wake: InboundWake, row: ConversationInboundEvent) -> None:
    try:
        wake(row)
    except Exception:
        logger.exception("inbound_event_dispatch_failed", inbound_event_id=str(row.id), source=row.source)


def _should_wake(row: ConversationInboundEvent, *, now: datetime) -> bool:
    if row.status == ConversationInboundEvent.Status.PENDING:
        return row.due_at <= now
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
    except IntegrityError as exc:
        try:
            with transaction.atomic():
                # Concurrent Slack retries can both hit IntegrityError. Lock the existing
                # row so retry metadata updates cannot race.
                row = (
                    ConversationInboundEvent.objects.for_team(team.id)
                    .select_for_update()
                    .get(source=source, source_id=source_id)
                )
                ConversationInboundEvent.objects.for_team(team.id).filter(id=row.id).update(
                    provider_retry_num=provider_retry_num,
                    provider_retry_reason=provider_retry_reason,
                    updated_at=timezone.now(),
                )
                row.refresh_from_db()
                return row
        except ConversationInboundEvent.DoesNotExist:
            # Unique conflict is the only IntegrityError that leaves a row to replay.
            raise exc from None


def accept_inbound_event(
    *,
    team: Team,
    source: str,
    source_id: str,
    provider_account_id: str,
    payload: dict[str, Any] | None,
    provider_retry_num: int | None,
    provider_retry_reason: str,
    wake: InboundWake,
) -> ConversationInboundEvent:
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
        if _should_wake(row, now=timezone.now()):
            transaction.on_commit(lambda: _safe_wake(wake, row))
    return row


def _fail_row_without_claim(
    row: ConversationInboundEvent,
    *,
    now: datetime,
    error_code: str,
    error: str,
) -> None:
    row.status = ConversationInboundEvent.Status.FAILED
    row.terminal_at = now
    row.lease_expires_at = None
    row.last_error_code = error_code
    row.last_error = error[:INBOUND_ERROR_MAX_LENGTH]
    row.save(
        update_fields=[
            "status",
            "terminal_at",
            "lease_expires_at",
            "last_error_code",
            "last_error",
            "updated_at",
        ]
    )
    transaction.on_commit(lambda: INBOUND_ATTEMPTS_TOTAL.labels(source=row.source, result="failed").inc())


def claim_inbound_event(inbound_event_id: str) -> InboundClaim | None:
    now = timezone.now()
    lease_until = now + timedelta(seconds=INBOUND_LEASE_SECONDS)
    with transaction.atomic():
        row = (
            # nosemgrep: idor-lookup-without-team (cross-team worker; ID comes from the committed receipt dispatch)
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
        if row.created_at < now - INBOUND_MAX_AGE:
            _fail_row_without_claim(
                row,
                now=now,
                error_code="max_age",
                error="Exceeded inbound processing age",
            )
            return None
        if row.attempts >= INBOUND_MAX_ATTEMPTS:
            _fail_row_without_claim(
                row,
                now=now,
                error_code="max_attempts",
                error=f"Exceeded {INBOUND_MAX_ATTEMPTS} processing attempts",
            )
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


def _fenced(claim: InboundClaim) -> QuerySet[ConversationInboundEvent]:
    # Retry leaves the same fencing token on a PENDING row. Status must still be
    # PROCESSING so a later complete or fail cannot settle work that was released.
    return ConversationInboundEvent.objects.unscoped().filter(  # nosemgrep: idor-lookup-without-team (ID comes from the claimed row)
        id=claim.event.id,
        fencing_token=claim.event.fencing_token,
        status=ConversationInboundEvent.Status.PROCESSING,
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


def _pending_inbound_events(*, now: datetime) -> QuerySet[ConversationInboundEvent]:
    return ConversationInboundEvent.objects.unscoped().filter(
        status=ConversationInboundEvent.Status.PENDING,
        due_at__lte=now,
    )


def _expired_inbound_events(*, now: datetime) -> QuerySet[ConversationInboundEvent]:
    return ConversationInboundEvent.objects.unscoped().filter(
        status=ConversationInboundEvent.Status.PROCESSING,
        lease_expires_at__lte=now,
    )


def due_inbound_event_ids(*, limit: int, now: datetime) -> list[tuple[UUID, str]]:
    pending = list(_pending_inbound_events(now=now).order_by("due_at").values_list("id", "source", "due_at")[:limit])
    expired = list(
        _expired_inbound_events(now=now)
        .order_by("lease_expires_at")
        .values_list("id", "source", "lease_expires_at")[:limit]
    )
    ready = sorted([*pending, *expired], key=lambda row: cast(datetime, row[2]))
    return [(event_id, source) for event_id, source, _ in ready[:limit]]


def cleanup_inbound_payloads(now: datetime, *, limit: int = INBOUND_SWEEP_BATCH_SIZE) -> int:
    cutoff = now - INBOUND_PAYLOAD_TTL
    event_ids = list(
        ConversationInboundEvent.objects.unscoped()
        .filter(
            status__in=ConversationInboundEvent.TERMINAL_STATUSES,
            payload__isnull=False,
            terminal_at__lte=cutoff,
        )
        .order_by("terminal_at")
        .values_list("id", flat=True)[:limit]
    )
    # nosemgrep: idor-lookup-without-team (IDs come from the cross-team retention query above)
    return ConversationInboundEvent.objects.unscoped().filter(id__in=event_ids).update(payload=None, updated_at=now)


def delete_inbound_tombstones(now: datetime, *, limit: int = INBOUND_SWEEP_BATCH_SIZE) -> int:
    cutoff = now - INBOUND_TOMBSTONE_TTL
    event_ids = list(
        ConversationInboundEvent.objects.unscoped()
        .filter(
            status__in=ConversationInboundEvent.TERMINAL_STATUSES,
            terminal_at__lte=cutoff,
        )
        .order_by("terminal_at")
        .values_list("id", flat=True)[:limit]
    )
    # nosemgrep: idor-lookup-without-team (IDs come from the cross-team retention query above)
    deleted, _ = ConversationInboundEvent.objects.unscoped().filter(id__in=event_ids).delete()
    return deleted


def drain_inbound_retention(cleanup: Callable[[datetime], int], now: datetime) -> int:
    total = 0
    for _ in range(INBOUND_SWEEP_MAX_ROUNDS):
        cleaned = cleanup(now)
        total += cleaned
        if cleaned < INBOUND_SWEEP_BATCH_SIZE:
            break
    return total


def _push_inbound_queue_gauges(*, backlog: list[tuple[str, str, int]], oldest_age: float, now: datetime) -> None:
    """Push the inbound queue snapshot as region-scoped gauges.

    These values describe the whole receipt table, not the pod that measured them.
    A module-level gauge would make every worker that swept export its own snapshot.
    ``multiprocess_mode`` writes PROMETHEUS_MULTIPROC_DIR even on a throwaway
    registry, so the value would reappear on every worker /metrics scrape.
    """
    with pushed_metrics_registry("conversations_inbound_queue") as registry:
        backlog_gauge = Gauge(
            "posthog_conversations_inbound_backlog",
            "Non-terminal inbound callback receipts by status and source",
            labelnames=["status", "source"],
            registry=registry,
        )
        for status, source, count in backlog:
            backlog_gauge.labels(status=status, source=source).set(count)
        Gauge(
            "posthog_conversations_inbound_oldest_ready_age_seconds",
            "Age in seconds of the oldest due or expired-lease inbound receipt",
            registry=registry,
        ).set(oldest_age)
        # Pushgateway gauges never expire. Without this, a dead sweeper freezes an empty
        # backlog forever and a backlog alert can never fire.
        Gauge(
            "posthog_conversations_inbound_last_sweep_timestamp_seconds",
            "Unix timestamp of the last completed inbound queue sweep",
            registry=registry,
        ).set(now.timestamp())


def record_inbound_queue_metrics(now: datetime) -> InboundQueueMetrics:
    oldest_age = 0.0
    counts = {
        ConversationInboundEvent.Status.PENDING: 0,
        ConversationInboundEvent.Status.PROCESSING: 0,
    }
    backlog: list[tuple[str, str, int]] = []
    for source in ConversationInboundEventSource.values:
        for status in (ConversationInboundEvent.Status.PENDING, ConversationInboundEvent.Status.PROCESSING):
            count = ConversationInboundEvent.objects.unscoped().filter(source=source, status=status).count()
            backlog.append((status, source, count))
            counts[status] += count
    oldest_pending = _pending_inbound_events(now=now).order_by("due_at").values_list("due_at", flat=True).first()
    oldest_expired = (
        _expired_inbound_events(now=now).order_by("lease_expires_at").values_list("lease_expires_at", flat=True).first()
    )
    oldest = min((ready_at for ready_at in (oldest_pending, oldest_expired) if ready_at is not None), default=None)
    if oldest is not None:
        oldest_age = max((now - oldest).total_seconds(), 0.0)
    _push_inbound_queue_gauges(backlog=backlog, oldest_age=oldest_age, now=now)
    return InboundQueueMetrics(
        pending_count=counts[ConversationInboundEvent.Status.PENDING],
        processing_count=counts[ConversationInboundEvent.Status.PROCESSING],
        oldest_ready_age_seconds=oldest_age,
    )


def inbound_event_payload_event(row: ConversationInboundEvent) -> dict[str, Any] | None:
    payload = row.payload
    if not isinstance(payload, dict):
        return None
    inner = payload.get("event")
    if isinstance(inner, dict):
        return inner
    return None
