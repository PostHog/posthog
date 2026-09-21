from __future__ import annotations

import random
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

import structlog
from prometheus_client import Gauge

from posthog.comment.formatting import extract_images_from_rich_content, rich_content_to_slack_payload
from posthog.dataclasses import frozen
from posthog.metrics import pushed_metrics_registry
from posthog.models.comment import Comment
from posthog.models.team import Team

from products.conversations.backend.metrics import DELIVERY_ATTEMPTS_TOTAL, DELIVERY_LEASES_TOTAL
from products.conversations.backend.models import (
    ConversationDelivery,
    ConversationDeliveryChannel,
    ConversationDeliveryPart,
    TeamConversationsSlackConfig,
)
from products.conversations.backend.models.constants import Channel
from products.conversations.backend.models.delivery import (
    DELIVERY_ERROR_MAX_LENGTH,
    DeliverySnapshotTooLargeError,
    reject_oversized_delivery_snapshot,
)
from products.conversations.backend.models.ticket import Ticket

logger = structlog.get_logger(__name__)

DELIVERY_PART_KEY_BODY = "body"
# Covers a crashed worker for one Slack chat.postMessage. The claim transaction
# releases before the HTTP call, so this is reclaim latency, not a handler wall-clock.
DELIVERY_LEASE_SECONDS = 5 * 60
DELIVERY_MAX_ATTEMPTS = 20
DELIVERY_BACKOFF_BASE_SECONDS = 15
DELIVERY_BACKOFF_MAX_SECONDS = 15 * 60
DELIVERY_MAX_AGE = timedelta(hours=24)
DELIVERY_SNAPSHOT_TTL = timedelta(hours=24)
DELIVERY_SWEEP_BATCH_SIZE = 100
DELIVERY_SWEEP_MAX_ROUNDS = 20
DELIVERY_RETRY_AFTER_MAX_SECONDS = 60 * 60

DeliveryWake = Callable[[ConversationDeliveryPart], object]


class TransientDeliveryError(Exception):
    """Work that should be retried from the Postgres part rather than Celery retry."""

    def __init__(self, message: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class PermanentDeliveryError(Exception):
    """Work that must not be retried, such as a revoked Slack token."""

    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@frozen
class DeliveryClaim:
    part: ConversationDeliveryPart
    allow_retry: bool
    expired_reclaim: bool


@frozen
class CommentAuthor:
    name: str
    email: str


@frozen
class DeliveryQueueMetrics:
    pending_count: int
    processing_count: int
    oldest_ready_age_seconds: float


def retry_delay_seconds(attempts: int, *, retry_after_seconds: int | None = None) -> int:
    if retry_after_seconds is not None:
        return max(min(retry_after_seconds, DELIVERY_RETRY_AFTER_MAX_SECONDS), 1)
    exponent = max(attempts - 1, 0)
    backoff = min(DELIVERY_BACKOFF_BASE_SECONDS * (2 ** min(exponent, 8)), DELIVERY_BACKOFF_MAX_SECONDS)
    jitter = random.uniform(0, backoff * 0.5)
    return max(int(backoff + jitter), 1)


def _safe_wake(wake: DeliveryWake, row: ConversationDeliveryPart) -> None:
    try:
        wake(row)
    except Exception:
        logger.exception("delivery_part_dispatch_failed", delivery_part_id=str(row.id), part_key=row.part_key)


def _workspace_id_for_team(team: Team) -> str | None:
    team_ids = [team.id]
    if team.parent_team_id:
        team_ids.append(team.parent_team_id)
    configs = {
        config.team_id: config.slack_team_id
        for config in TeamConversationsSlackConfig.objects.filter(team_id__in=team_ids)
        .exclude(slack_team_id="")
        .exclude(slack_team_id__isnull=True)
        .only("team_id", "slack_team_id")
    }
    own = configs.get(team.id)
    if own:
        return own
    if team.parent_team_id:
        return configs.get(team.parent_team_id)
    return None


def _image_refs(rich_content: dict[str, Any] | None) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for image in extract_images_from_rich_content(rich_content):
        url = image.get("url")
        if not isinstance(url, str) or not url:
            continue
        alt = image.get("alt")
        refs.append({"url": url, "alt": alt if isinstance(alt, str) and alt else "image"})
    return refs


def _author_for_comment(comment: Comment, team: Team) -> CommentAuthor:
    created_by = comment.created_by
    if created_by:
        name = f"{created_by.first_name} {created_by.last_name}".strip() or created_by.email
        return CommentAuthor(name=name, email=created_by.email or "")
    settings_dict = team.conversations_settings or {}
    bot_name = settings_dict.get("slack_bot_display_name")
    return CommentAuthor(name=bot_name if isinstance(bot_name, str) and bot_name else "AI assistant", email="")


def _ticket_belongs_to_comment_team(ticket: Ticket, comment: Comment) -> bool:
    # Comment is project-scoped (RootTeamMixin). Ticket is environment-scoped.
    ticket_root_id = ticket.team.parent_team_id or ticket.team_id
    return ticket_root_id == comment.team_id


def _body_snapshot(
    comment: Comment,
    *,
    team: Team,
    author: CommentAuthor,
    media_team_id: int,
) -> dict[str, Any]:
    slack_text, slack_blocks = rich_content_to_slack_payload(
        comment.rich_content,
        comment.content or "",
        include_images=False,
        organization_id=team.organization_id,
    )
    return {
        "text": slack_text,
        "blocks": slack_blocks,
        "author_name": author.name,
        "author_email": author.email,
        "media_team_id": media_team_id,
        "images": _image_refs(comment.rich_content if isinstance(comment.rich_content, dict) else None),
    }


def _enqueue_failed_slack_body(
    comment: Comment,
    *,
    ticket: Ticket,
    workspace_id: str,
    route: dict[str, Any],
    error_code: str,
    error: str,
) -> ConversationDeliveryPart:
    now = timezone.now()
    bounded = error[:DELIVERY_ERROR_MAX_LENGTH]
    with transaction.atomic():
        delivery, _ = ConversationDelivery.objects.for_team(comment.team_id).get_or_create(
            channel=ConversationDeliveryChannel.SLACK,
            comment_id=comment.id,
            defaults={
                "team": comment.team,
                "ticket_id": ticket.id,
                "provider_account_id": workspace_id,
                "route": route,
                "status": ConversationDelivery.Status.FAILED,
                "terminal_at": now,
                "last_error_code": error_code,
                "last_error": bounded,
            },
        )
        part, _ = ConversationDeliveryPart.objects.for_team(delivery.team_id).get_or_create(
            delivery=delivery,
            part_key=DELIVERY_PART_KEY_BODY,
            defaults={
                "team": delivery.team,
                "client_msg_id": str(uuid4()),
                "route": route,
                "payload": None,
                "status": ConversationDeliveryPart.Status.FAILED,
                "terminal_at": now,
                "last_error_code": error_code,
                "last_error": bounded,
            },
        )
    return part


def enqueue_slack_body_delivery(comment: Comment) -> ConversationDeliveryPart | None:
    """Create the Slack delivery and body part in the caller's transaction.

    Snapshot the destination and body here so a later comment edit cannot change
    what we post. Celery dispatch stays with the caller via ``transaction.on_commit``.
    """
    if not comment.item_id:
        return None
    ticket = (
        # nosemgrep: idor-lookup-without-team (ticket id comes from the comment just saved; canonical team is checked next)
        Ticket.objects.filter(
            id=comment.item_id,
            channel_source=Channel.SLACK,
        )
        .select_related("team")
        .first()
    )
    if (
        ticket is None
        or not _ticket_belongs_to_comment_team(ticket, comment)
        or not ticket.slack_channel_id
        or not ticket.slack_thread_ts
    ):
        return None
    workspace_id = _workspace_id_for_team(ticket.team)
    if workspace_id is None:
        return None

    snapshot = _body_snapshot(
        comment,
        team=comment.team,
        author=_author_for_comment(comment, comment.team),
        media_team_id=ticket.team_id,
    )
    route = {"channel": ticket.slack_channel_id, "thread_ts": ticket.slack_thread_ts}

    try:
        reject_oversized_delivery_snapshot(snapshot, field="payload")
        reject_oversized_delivery_snapshot(route, field="route")
    except DeliverySnapshotTooLargeError as exc:
        # Fail the part only. Raising here would roll back the agent's comment.
        return _enqueue_failed_slack_body(
            comment,
            ticket=ticket,
            workspace_id=workspace_id,
            route=route,
            error_code="payload_too_large",
            error=str(exc),
        )

    with transaction.atomic():
        delivery, _ = ConversationDelivery.objects.for_team(comment.team_id).get_or_create(
            channel=ConversationDeliveryChannel.SLACK,
            comment_id=comment.id,
            defaults={
                "team": comment.team,
                "ticket_id": ticket.id,
                "provider_account_id": workspace_id,
                "route": route,
            },
        )
        part, _ = ConversationDeliveryPart.objects.for_team(delivery.team_id).get_or_create(
            delivery=delivery,
            part_key=DELIVERY_PART_KEY_BODY,
            defaults={
                "team": delivery.team,
                "client_msg_id": str(uuid4()),
                "route": route,
                "payload": snapshot,
            },
        )
    return part


def _delivery_row(*, team_id: int, delivery_id: UUID) -> QuerySet[ConversationDelivery]:
    """Scope the parent delivery by the part's team.

    ``team`` on both rows is the canonical root team, and the composite FK keeps a
    part on its parent's team, so ``canonical=True`` skips a Team lookup per write.
    """
    return ConversationDelivery.objects.for_team(team_id, canonical=True).filter(id=delivery_id)


def _fail_part_without_claim(
    row: ConversationDeliveryPart,
    *,
    now: datetime,
    error_code: str,
    error: str,
) -> None:
    row.status = ConversationDeliveryPart.Status.FAILED
    row.terminal_at = now
    row.lease_expires_at = None
    row.last_error_code = error_code
    row.last_error = error[:DELIVERY_ERROR_MAX_LENGTH]
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
    _delivery_row(team_id=row.team_id, delivery_id=row.delivery_id).update(
        status=ConversationDelivery.Status.FAILED,
        terminal_at=now,
        lease_expires_at=None,
        last_error_code=error_code,
        last_error=error[:DELIVERY_ERROR_MAX_LENGTH],
        updated_at=now,
    )
    transaction.on_commit(lambda: DELIVERY_ATTEMPTS_TOTAL.labels(part_key=row.part_key, result="failed").inc())


def claim_delivery_part(delivery_part_id: str) -> DeliveryClaim | None:
    now = timezone.now()
    lease_until = now + timedelta(seconds=DELIVERY_LEASE_SECONDS)
    with transaction.atomic():
        row = (
            # nosemgrep: idor-lookup-without-team (cross-team worker; ID comes from the committed part dispatch)
            ConversationDeliveryPart.objects.unscoped()
            .select_for_update(skip_locked=True)
            .select_related("delivery")
            .filter(id=delivery_part_id)
            .filter(
                Q(status=ConversationDeliveryPart.Status.PENDING, due_at__lte=now)
                | Q(status=ConversationDeliveryPart.Status.PROCESSING, lease_expires_at__lte=now)
            )
            .first()
        )
        if row is None:
            DELIVERY_LEASES_TOTAL.labels(result="busy").inc()
            return None
        if (row.redriven_at or row.created_at) < now - DELIVERY_MAX_AGE:
            _fail_part_without_claim(
                row,
                now=now,
                error_code="max_age",
                error="Exceeded delivery processing age",
            )
            return None
        if row.attempts >= DELIVERY_MAX_ATTEMPTS:
            _fail_part_without_claim(
                row,
                now=now,
                error_code="max_attempts",
                error=f"Exceeded {DELIVERY_MAX_ATTEMPTS} processing attempts",
            )
            return None
        expired_reclaim = row.status == ConversationDeliveryPart.Status.PROCESSING
        row.status = ConversationDeliveryPart.Status.PROCESSING
        row.lease_expires_at = lease_until
        row.fencing_token += 1
        row.attempts += 1
        row.save(update_fields=["status", "lease_expires_at", "fencing_token", "attempts", "updated_at"])
    DELIVERY_LEASES_TOTAL.labels(result="expired_reclaim" if expired_reclaim else "claimed").inc()
    DELIVERY_ATTEMPTS_TOTAL.labels(part_key=row.part_key, result="claimed").inc()
    return DeliveryClaim(
        part=row,
        allow_retry=row.attempts < DELIVERY_MAX_ATTEMPTS,
        expired_reclaim=expired_reclaim,
    )


def _fenced(claim: DeliveryClaim) -> QuerySet[ConversationDeliveryPart]:
    return ConversationDeliveryPart.objects.for_team(claim.part.team_id, canonical=True).filter(
        id=claim.part.id,
        fencing_token=claim.part.fencing_token,
        status=ConversationDeliveryPart.Status.PROCESSING,
    )


def _roll_up_delivery(
    claim: DeliveryClaim,
    *,
    now: datetime,
    status: str,
    provider_message_id: str = "",
    error_code: str = "",
    error: str = "",
    accepted_at: datetime | None = None,
) -> None:
    fields: dict[str, Any] = {
        "status": status,
        "terminal_at": now if status in ConversationDelivery.TERMINAL_STATUSES else None,
        "lease_expires_at": None,
        "last_error_code": error_code,
        "last_error": error[:DELIVERY_ERROR_MAX_LENGTH],
        "updated_at": now,
    }
    if status != ConversationDelivery.Status.FAILED:
        # One part failing must not erase the provider correlation an earlier part won.
        fields["provider_message_id"] = provider_message_id
        fields["accepted_at"] = accepted_at
    _delivery_row(team_id=claim.part.team_id, delivery_id=claim.part.delivery_id).update(**fields)


def accept_delivery_part(claim: DeliveryClaim, *, provider_message_id: str = "") -> bool:
    now = timezone.now()
    message_id = provider_message_id[:255]
    # Part and parent must commit together so a crash cannot leave an accepted
    # body on a pending delivery.
    with transaction.atomic():
        updated = _fenced(claim).update(
            status=ConversationDeliveryPart.Status.ACCEPTED,
            terminal_at=now,
            accepted_at=now,
            lease_expires_at=None,
            provider_message_id=message_id,
            last_error_code="",
            last_error="",
            updated_at=now,
        )
        if not updated:
            return False
        _roll_up_delivery(
            claim,
            now=now,
            status=ConversationDelivery.Status.ACCEPTED,
            provider_message_id=message_id,
            accepted_at=now,
        )
    DELIVERY_ATTEMPTS_TOTAL.labels(part_key=claim.part.part_key, result="accepted").inc()
    return True


def fail_delivery_part(claim: DeliveryClaim, *, error_code: str, error: str) -> bool:
    now = timezone.now()
    bounded_error = error[:DELIVERY_ERROR_MAX_LENGTH]
    with transaction.atomic():
        updated = _fenced(claim).update(
            status=ConversationDeliveryPart.Status.FAILED,
            terminal_at=now,
            lease_expires_at=None,
            last_error_code=error_code,
            last_error=bounded_error,
            updated_at=now,
        )
        if not updated:
            return False
        _roll_up_delivery(
            claim,
            now=now,
            status=ConversationDelivery.Status.FAILED,
            error_code=error_code,
            error=bounded_error,
        )
    DELIVERY_ATTEMPTS_TOTAL.labels(part_key=claim.part.part_key, result="failed").inc()
    return True


def schedule_delivery_retry(
    claim: DeliveryClaim,
    *,
    error_code: str,
    error: str,
    retry_after_seconds: int | None = None,
) -> int | None:
    delay = retry_delay_seconds(claim.part.attempts, retry_after_seconds=retry_after_seconds)
    now = timezone.now()
    bounded_error = error[:DELIVERY_ERROR_MAX_LENGTH]
    updated = _fenced(claim).update(
        status=ConversationDeliveryPart.Status.PENDING,
        due_at=now + timedelta(seconds=delay),
        lease_expires_at=None,
        last_error_code=error_code,
        last_error=bounded_error,
        updated_at=now,
    )
    if not updated:
        return None
    DELIVERY_ATTEMPTS_TOTAL.labels(part_key=claim.part.part_key, result="retry").inc()
    return delay


def _pending_delivery_parts(*, now: datetime) -> QuerySet[ConversationDeliveryPart]:
    return ConversationDeliveryPart.objects.unscoped().filter(
        status=ConversationDeliveryPart.Status.PENDING,
        due_at__lte=now,
    )


def _expired_delivery_parts(*, now: datetime) -> QuerySet[ConversationDeliveryPart]:
    return ConversationDeliveryPart.objects.unscoped().filter(
        status=ConversationDeliveryPart.Status.PROCESSING,
        lease_expires_at__lte=now,
    )


def due_delivery_part_ids(*, limit: int, now: datetime) -> list[UUID]:
    pending = list(_pending_delivery_parts(now=now).order_by("due_at").values_list("id", "due_at")[:limit])
    expired = list(
        _expired_delivery_parts(now=now).order_by("lease_expires_at").values_list("id", "lease_expires_at")[:limit]
    )
    ready = sorted([*pending, *expired], key=lambda row: cast(datetime, row[1]))
    return [part_id for part_id, _ in ready[:limit]]


def cleanup_delivery_snapshots(now: datetime, *, limit: int = DELIVERY_SWEEP_BATCH_SIZE) -> int:
    cutoff = now - DELIVERY_SNAPSHOT_TTL
    # Failed parts keep snapshots so manual redrive can still post the body.
    snapshot_gc_statuses = (
        ConversationDeliveryPart.Status.ACCEPTED,
        ConversationDeliveryPart.Status.DELIVERED,
    )
    part_ids = list(
        ConversationDeliveryPart.objects.unscoped()
        .filter(
            status__in=snapshot_gc_statuses,
            terminal_at__lte=cutoff,
        )
        .filter(Q(payload__isnull=False) | Q(route__isnull=False))
        .order_by("terminal_at")
        .values_list("id", flat=True)[:limit]
    )
    parts_cleaned = (
        # nosemgrep: idor-lookup-without-team (IDs come from the cross-team retention query above)
        ConversationDeliveryPart.objects.unscoped()
        .filter(id__in=part_ids)
        .update(payload=None, route=None, updated_at=now)
    )
    delivery_ids = list(
        ConversationDelivery.objects.unscoped()
        .filter(
            status__in=snapshot_gc_statuses,
            terminal_at__lte=cutoff,
        )
        .filter(Q(payload__isnull=False) | Q(route__isnull=False))
        .order_by("terminal_at")
        .values_list("id", flat=True)[:limit]
    )
    deliveries_cleaned = (
        # nosemgrep: idor-lookup-without-team (IDs come from the cross-team retention query above)
        ConversationDelivery.objects.unscoped()
        .filter(id__in=delivery_ids)
        .update(payload=None, route=None, updated_at=now)
    )
    return parts_cleaned + deliveries_cleaned


def drain_delivery_retention(cleanup: Callable[[datetime], int], now: datetime) -> int:
    total = 0
    for _ in range(DELIVERY_SWEEP_MAX_ROUNDS):
        cleaned = cleanup(now)
        total += cleaned
        if cleaned < DELIVERY_SWEEP_BATCH_SIZE:
            break
    return total


def _push_delivery_queue_gauges(*, backlog: list[tuple[str, str, int]], oldest_age: float, now: datetime) -> None:
    with pushed_metrics_registry("conversations_delivery_queue") as registry:
        backlog_gauge = Gauge(
            "posthog_conversations_delivery_backlog",
            "Non-terminal outbound delivery parts by status and part key",
            labelnames=["status", "part_key"],
            registry=registry,
        )
        for status, part_key, count in backlog:
            backlog_gauge.labels(status=status, part_key=part_key).set(count)
        Gauge(
            "posthog_conversations_delivery_oldest_ready_age_seconds",
            "Age in seconds of the oldest due or expired-lease delivery part",
            registry=registry,
        ).set(oldest_age)
        Gauge(
            "posthog_conversations_delivery_last_sweep_timestamp_seconds",
            "Unix timestamp of the last completed delivery queue sweep",
            registry=registry,
        ).set(now.timestamp())


def record_delivery_queue_metrics(now: datetime) -> DeliveryQueueMetrics:
    oldest_age = 0.0
    counts = {
        ConversationDeliveryPart.Status.PENDING: 0,
        ConversationDeliveryPart.Status.PROCESSING: 0,
    }
    backlog: list[tuple[str, str, int]] = []
    open_statuses = (ConversationDeliveryPart.Status.PENDING, ConversationDeliveryPart.Status.PROCESSING)
    grouped = {
        (row["part_key"], row["status"]): row["total"]
        for row in ConversationDeliveryPart.objects.unscoped()
        .filter(status__in=open_statuses)
        .values("part_key", "status")
        .annotate(total=Count("id"))
    }
    # Always report the body key so a drained queue still publishes a zero.
    for part_key in sorted({part_key for part_key, _ in grouped} | {DELIVERY_PART_KEY_BODY}):
        for status in open_statuses:
            count = grouped.get((part_key, status), 0)
            backlog.append((status, part_key, count))
            counts[status] += count
    oldest_pending = _pending_delivery_parts(now=now).order_by("due_at").values_list("due_at", flat=True).first()
    oldest_expired = (
        _expired_delivery_parts(now=now).order_by("lease_expires_at").values_list("lease_expires_at", flat=True).first()
    )
    oldest = min((ready_at for ready_at in (oldest_pending, oldest_expired) if ready_at is not None), default=None)
    if oldest is not None:
        oldest_age = max((now - oldest).total_seconds(), 0.0)
    _push_delivery_queue_gauges(backlog=backlog, oldest_age=oldest_age, now=now)
    return DeliveryQueueMetrics(
        pending_count=counts[ConversationDeliveryPart.Status.PENDING],
        processing_count=counts[ConversationDeliveryPart.Status.PROCESSING],
        oldest_ready_age_seconds=oldest_age,
    )


def slack_route_and_config_are_valid(part: ConversationDeliveryPart) -> bool:
    route = part.route if isinstance(part.route, dict) else {}
    channel = str(route.get("channel") or "")
    thread_ts = str(route.get("thread_ts") or "")
    if not channel or not thread_ts:
        return False
    delivery = part.delivery
    config = (
        TeamConversationsSlackConfig.objects.filter(
            slack_team_id=delivery.provider_account_id,
            slack_bot_token__isnull=False,
        )
        .select_related("team")
        .first()
    )
    if config is None:
        return False
    config_root_team_id = config.team.parent_team_id or config.team_id
    return config_root_team_id == delivery.team_id


def redrive_failed_delivery_part(part_id: str, *, wake: DeliveryWake) -> ConversationDeliveryPart | None:
    now = timezone.now()
    with transaction.atomic():
        part = (
            # nosemgrep: idor-lookup-without-team (manual redrive; ID is an explicit operator target)
            ConversationDeliveryPart.objects.unscoped()
            .select_for_update()
            .select_related("delivery")
            .filter(id=part_id, status=ConversationDeliveryPart.Status.FAILED)
            .first()
        )
        if part is None or not slack_route_and_config_are_valid(part):
            return None
        ConversationDeliveryPart.objects.for_team(part.team_id, canonical=True).filter(id=part.id).update(
            status=ConversationDeliveryPart.Status.PENDING,
            terminal_at=None,
            lease_expires_at=None,
            due_at=now,
            attempts=0,
            redriven_at=now,
            updated_at=now,
        )
        _delivery_row(team_id=part.team_id, delivery_id=part.delivery_id).update(
            status=ConversationDelivery.Status.PENDING,
            terminal_at=None,
            lease_expires_at=None,
            accepted_at=None,
            delivered_at=None,
            due_at=now,
            redriven_at=now,
            updated_at=now,
        )
        part.refresh_from_db()
        transaction.on_commit(lambda: _safe_wake(wake, part))
    return part
