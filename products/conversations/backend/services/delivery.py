from __future__ import annotations

import random
import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, cast
from urllib.parse import urlparse
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction
from django.db.models import Case, CharField, Count, Q, QuerySet, Value, When
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
from products.conversations.backend.models.constants import WORKFLOW_AUTHOR_TYPE, Channel
from products.conversations.backend.models.delivery import (
    DELIVERY_ERROR_MAX_LENGTH,
    DeliverySnapshotTooLargeError,
    reject_oversized_delivery_snapshot,
)
from products.conversations.backend.models.ticket import Ticket

logger = structlog.get_logger(__name__)

DELIVERY_PART_KEY_BODY = "body"
DELIVERY_PART_KEY_FALLBACK = "fallback"
DELIVERY_PART_KEY_IMAGE_PREFIX = "image:"
DELIVERY_METRIC_PART_KEY_IMAGE = "image"
DELIVERY_METRIC_PART_KEY_OTHER = "other"
IMAGE_UPLOAD_STEP_GET = "get_upload"
IMAGE_UPLOAD_STEP_BYTES = "byte_upload"
IMAGE_UPLOAD_STEP_COMPLETE = "complete_upload"
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
class SlackFallbackSnapshot:
    urls: list[str]
    author_name: str
    author_email: str
    route: dict[str, Any]


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


def is_slack_image_part_key(part_key: str) -> bool:
    return part_key.startswith(DELIVERY_PART_KEY_IMAGE_PREFIX) and len(part_key) > len(DELIVERY_PART_KEY_IMAGE_PREFIX)


def delivery_metric_part_key(part_key: str) -> str:
    # Unique image keys must not become Prometheus labels.
    if part_key == DELIVERY_PART_KEY_BODY or part_key == DELIVERY_PART_KEY_FALLBACK:
        return part_key
    if is_slack_image_part_key(part_key):
        return DELIVERY_METRIC_PART_KEY_IMAGE
    return DELIVERY_METRIC_PART_KEY_OTHER


def _rolls_up_parent(part: ConversationDeliveryPart) -> bool:
    return part.part_key == DELIVERY_PART_KEY_BODY


def slack_image_identity(image_url: str) -> str:
    parsed = urlparse(image_url)
    raw_id = parsed.path
    marker = "/uploaded_media/"
    if marker in parsed.path:
        raw_id = parsed.path.rsplit(marker, 1)[-1].strip("/")
    try:
        return str(UUID(raw_id))
    except ValueError:
        return hashlib.sha256(image_url.encode("utf-8")).hexdigest()[:32]


def slack_image_part_key(image_url: str) -> str:
    return f"{DELIVERY_PART_KEY_IMAGE_PREFIX}{slack_image_identity(image_url)}"


def _increment_delivery_attempt(part_key: str, result: str) -> None:
    DELIVERY_ATTEMPTS_TOTAL.labels(part_key=delivery_metric_part_key(part_key), result=result).inc()


def _author_for_comment(comment: Comment, team: Team) -> CommentAuthor:
    created_by = comment.created_by
    if created_by:
        name = f"{created_by.first_name} {created_by.last_name}".strip() or created_by.email
        return CommentAuthor(name=name, email=created_by.email or "")
    settings_dict = team.conversations_settings or {}
    bot_name = settings_dict.get("slack_bot_display_name")
    context = comment.item_context if isinstance(comment.item_context, dict) else {}
    # A workflow reply is not the assistant. Fall back to Support when the team has no bot name.
    fallback = "Support" if context.get("author_type") == WORKFLOW_AUTHOR_TYPE else "AI assistant"
    return CommentAuthor(name=bot_name if isinstance(bot_name, str) and bot_name else fallback, email="")


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
    if _rolls_up_parent(row):
        _delivery_row(team_id=row.team_id, delivery_id=row.delivery_id).update(
            status=ConversationDelivery.Status.FAILED,
            terminal_at=now,
            lease_expires_at=None,
            last_error_code=error_code,
            last_error=error[:DELIVERY_ERROR_MAX_LENGTH],
            updated_at=now,
        )
    transaction.on_commit(lambda: _increment_delivery_attempt(row.part_key, "failed"))


def claim_delivery_part(delivery_part_id: str) -> DeliveryClaim | None:
    now = timezone.now()
    lease_until = now + timedelta(seconds=DELIVERY_LEASE_SECONDS)
    failed_part: ConversationDeliveryPart | None = None
    claim: DeliveryClaim | None = None
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
            failed_part = row
        elif row.attempts >= DELIVERY_MAX_ATTEMPTS:
            _fail_part_without_claim(
                row,
                now=now,
                error_code="max_attempts",
                error=f"Exceeded {DELIVERY_MAX_ATTEMPTS} processing attempts",
            )
            failed_part = row
        else:
            expired_reclaim = row.status == ConversationDeliveryPart.Status.PROCESSING
            row.status = ConversationDeliveryPart.Status.PROCESSING
            row.lease_expires_at = lease_until
            row.fencing_token += 1
            row.attempts += 1
            row.save(update_fields=["status", "lease_expires_at", "fencing_token", "attempts", "updated_at"])
            claim = DeliveryClaim(
                part=row,
                allow_retry=row.attempts < DELIVERY_MAX_ATTEMPTS,
                expired_reclaim=expired_reclaim,
            )
    if failed_part is not None:
        # Enqueue fallback after this transaction releases the claimed row.
        # maybe_enqueue_slack_fallback locks every image part in part_key order;
        # doing that while this claim still holds one image row deadlocks a concurrent settler.
        maybe_enqueue_slack_fallback(failed_part)
        return None
    if claim is None:
        return None
    DELIVERY_LEASES_TOTAL.labels(result="expired_reclaim" if claim.expired_reclaim else "claimed").inc()
    _increment_delivery_attempt(claim.part.part_key, "claimed")
    return claim


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


def _accept_delivery_part_locked(
    claim: DeliveryClaim,
    *,
    now: datetime,
    provider_message_id: str,
) -> bool:
    message_id = provider_message_id[:255]
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
    if _rolls_up_parent(claim.part):
        # Body accept and parent roll-up commit together so a crash cannot leave
        # an accepted body on a pending delivery. Attachment accepts leave the
        # parent's Slack ts alone.
        _roll_up_delivery(
            claim,
            now=now,
            status=ConversationDelivery.Status.ACCEPTED,
            provider_message_id=message_id,
            accepted_at=now,
        )
    return True


def accept_delivery_part(claim: DeliveryClaim, *, provider_message_id: str = "") -> bool:
    now = timezone.now()
    with transaction.atomic():
        accepted = _accept_delivery_part_locked(claim, now=now, provider_message_id=provider_message_id)
    if not accepted:
        return False
    _increment_delivery_attempt(claim.part.part_key, "accepted")
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
        if _rolls_up_parent(claim.part):
            _roll_up_delivery(
                claim,
                now=now,
                status=ConversationDelivery.Status.FAILED,
                error_code=error_code,
                error=bounded_error,
            )
    _increment_delivery_attempt(claim.part.part_key, "failed")
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
    _increment_delivery_attempt(claim.part.part_key, "retry")
    return delay


def defer_delivery_part(claim: DeliveryClaim, *, seconds: int, reason: str) -> bool:
    """Re-arm a claimed part for a wait that is not a failed attempt.

    The claim charged an attempt on the way in. Refund it, because a part that
    waits on another part must not spend the retry budget that real Slack
    failures need. DELIVERY_MAX_AGE still bounds the wait.
    """
    now = timezone.now()
    updated = _fenced(claim).update(
        status=ConversationDeliveryPart.Status.PENDING,
        due_at=now + timedelta(seconds=seconds),
        lease_expires_at=None,
        attempts=max(claim.part.attempts - 1, 0),
        last_error_code=reason,
        last_error="",
        updated_at=now,
    )
    if not updated:
        return False
    _increment_delivery_attempt(claim.part.part_key, "deferred")
    return True


def persist_delivery_part_payload(claim: DeliveryClaim, payload: dict[str, Any]) -> bool:
    reject_oversized_delivery_snapshot(payload, field="payload")
    now = timezone.now()
    updated = _fenced(claim).update(payload=payload, updated_at=now)
    if not updated:
        return False
    claim.part.payload = payload
    return True


def _enqueue_slack_attachment_parts(body_part: ConversationDeliveryPart) -> list[ConversationDeliveryPart]:
    payload = body_part.payload if isinstance(body_part.payload, dict) else {}
    images = payload.get("images")
    if not isinstance(images, list) or not images:
        return []
    route = body_part.route if isinstance(body_part.route, dict) else None
    if route is None:
        return []
    media_team_id = payload.get("media_team_id")
    if not isinstance(media_team_id, int):
        media_team_id = body_part.team_id
    follow_ups: list[ConversationDeliveryPart] = []
    seen_keys: set[str] = set()
    for image in images:
        if not isinstance(image, dict):
            continue
        url = image.get("url")
        if not isinstance(url, str) or not url:
            continue
        part_key = slack_image_part_key(url)
        if part_key in seen_keys:
            continue
        seen_keys.add(part_key)
        alt = image.get("alt")
        image_payload = {
            "url": url,
            "alt": alt if isinstance(alt, str) else "",
            "media_team_id": media_team_id,
            "author_name": str(payload.get("author_name") or ""),
            "author_email": str(payload.get("author_email") or ""),
            "step": IMAGE_UPLOAD_STEP_GET,
        }
        try:
            reject_oversized_delivery_snapshot(image_payload, field="payload")
        except DeliverySnapshotTooLargeError:
            logger.warning(
                "slack_delivery_image_snapshot_too_large",
                delivery_id=str(body_part.delivery_id),
                part_key=part_key,
            )
            continue
        part, _created = ConversationDeliveryPart.objects.for_team(body_part.team_id, canonical=True).get_or_create(
            delivery_id=body_part.delivery_id,
            part_key=part_key,
            defaults={
                "team_id": body_part.team_id,
                "route": route,
                "payload": image_payload,
            },
        )
        if part.status == ConversationDeliveryPart.Status.PENDING:
            follow_ups.append(part)
    return follow_ups


def complete_slack_body_delivery(claim: DeliveryClaim, *, provider_message_id: str) -> list[ConversationDeliveryPart]:
    # Enqueue image parts in the body-accept transaction so a crash after Slack
    # accepts the body cannot drop the attachments.
    now = timezone.now()
    with transaction.atomic():
        if not _accept_delivery_part_locked(claim, now=now, provider_message_id=provider_message_id):
            return []
        follow_ups = _enqueue_slack_attachment_parts(claim.part)
    _increment_delivery_attempt(claim.part.part_key, "accepted")
    return follow_ups


def _image_parts_for_delivery(*, team_id: int, delivery_id: UUID) -> QuerySet[ConversationDeliveryPart]:
    return (
        ConversationDeliveryPart.objects.for_team(team_id, canonical=True)
        .filter(
            delivery_id=delivery_id,
            part_key__startswith=DELIVERY_PART_KEY_IMAGE_PREFIX,
        )
        .order_by("part_key")
    )


def _slack_fallback_snapshot(image_parts: list[ConversationDeliveryPart]) -> SlackFallbackSnapshot | None:
    if not image_parts:
        return None
    if any(part.status not in ConversationDeliveryPart.TERMINAL_STATUSES for part in image_parts):
        return None
    failed_urls: list[str] = []
    author_name = ""
    author_email = ""
    route: dict[str, Any] | None = None
    for part in image_parts:
        payload = part.payload if isinstance(part.payload, dict) else {}
        if not author_name:
            author_name = str(payload.get("author_name") or "")
            author_email = str(payload.get("author_email") or "")
        if route is None and isinstance(part.route, dict):
            route = part.route
        if part.status != ConversationDeliveryPart.Status.FAILED:
            continue
        url = payload.get("url")
        if isinstance(url, str) and url:
            failed_urls.append(url)
    return SlackFallbackSnapshot(
        urls=list(dict.fromkeys(failed_urls)),
        author_name=author_name,
        author_email=author_email,
        route=route or {},
    )


def slack_fallback_payload(snapshot: SlackFallbackSnapshot) -> dict[str, Any]:
    return {
        "text": "Images:\n" + "\n".join(snapshot.urls),
        "urls": snapshot.urls,
        "author_name": snapshot.author_name,
        "author_email": snapshot.author_email,
    }


def pin_slack_fallback_payload(claim: DeliveryClaim) -> SlackFallbackSnapshot | None:
    """Record the failed-image set on the claimed fallback part, or report a wait.

    The image rows stay locked while the payload is written, so a redrive either
    lands before the read and returns None for a wait, or lands after the set
    this fallback posts is on the row.
    """
    with transaction.atomic():
        snapshot = _slack_fallback_snapshot(
            list(
                _image_parts_for_delivery(
                    team_id=claim.part.team_id, delivery_id=claim.part.delivery_id
                ).select_for_update()
            )
        )
        if snapshot is None:
            return None
        if not persist_delivery_part_payload(claim, slack_fallback_payload(snapshot)):
            return None
        return snapshot


def _rearm_slack_fallback(
    part: ConversationDeliveryPart,
    *,
    snapshot: SlackFallbackSnapshot,
    now: datetime,
) -> ConversationDeliveryPart | None:
    if part.status != ConversationDeliveryPart.Status.PENDING:
        # A claimed fallback is already posting, and a terminal one is an
        # operator's to redrive.
        return None
    payload = slack_fallback_payload(snapshot)
    try:
        reject_oversized_delivery_snapshot(payload, field="payload")
    except DeliverySnapshotTooLargeError:
        logger.warning(
            "slack_delivery_fallback_snapshot_too_large",
            delivery_id=str(part.delivery_id),
        )
        return None
    due_at = min(part.due_at, now)
    ConversationDeliveryPart.objects.for_team(part.team_id, canonical=True).filter(id=part.id).update(
        payload=payload,
        due_at=due_at,
        updated_at=now,
    )
    part.payload = payload
    part.due_at = due_at
    return part


def maybe_enqueue_slack_fallback(settled_part: ConversationDeliveryPart) -> ConversationDeliveryPart | None:
    """Return the fallback part to wake once every image part of the delivery has settled.

    A redrive can move an image out of a terminal state after the fallback row
    exists, so a fallback that is already waiting is re-armed with the current
    failed URLs rather than left for the sweeper with a stale list.
    """
    if not is_slack_image_part_key(settled_part.part_key):
        return None
    now = timezone.now()
    with transaction.atomic():
        snapshot = _slack_fallback_snapshot(
            list(
                _image_parts_for_delivery(
                    team_id=settled_part.team_id, delivery_id=settled_part.delivery_id
                ).select_for_update()
            )
        )
        if snapshot is None:
            return None
        existing = (
            ConversationDeliveryPart.objects.for_team(settled_part.team_id, canonical=True)
            .select_for_update()
            .filter(delivery_id=settled_part.delivery_id, part_key=DELIVERY_PART_KEY_FALLBACK)
            .first()
        )
        if existing is not None:
            return _rearm_slack_fallback(existing, snapshot=snapshot, now=now)
        if not snapshot.urls or not snapshot.route:
            return None
        fallback_payload = slack_fallback_payload(snapshot)
        try:
            reject_oversized_delivery_snapshot(fallback_payload, field="payload")
            reject_oversized_delivery_snapshot(snapshot.route, field="route")
        except DeliverySnapshotTooLargeError:
            logger.warning(
                "slack_delivery_fallback_snapshot_too_large",
                delivery_id=str(settled_part.delivery_id),
            )
            return None
        try:
            part, created = ConversationDeliveryPart.objects.for_team(
                settled_part.team_id, canonical=True
            ).get_or_create(
                delivery_id=settled_part.delivery_id,
                part_key=DELIVERY_PART_KEY_FALLBACK,
                defaults={
                    "team_id": settled_part.team_id,
                    "route": snapshot.route,
                    "payload": fallback_payload,
                    "client_msg_id": str(uuid4()),
                },
            )
        except IntegrityError:
            return None
        if not created:
            return None
        return part


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
    metric_key = Case(
        When(part_key=DELIVERY_PART_KEY_BODY, then=Value(DELIVERY_PART_KEY_BODY)),
        When(part_key=DELIVERY_PART_KEY_FALLBACK, then=Value(DELIVERY_PART_KEY_FALLBACK)),
        When(part_key__startswith=DELIVERY_PART_KEY_IMAGE_PREFIX, then=Value(DELIVERY_METRIC_PART_KEY_IMAGE)),
        default=Value(DELIVERY_METRIC_PART_KEY_OTHER),
        output_field=CharField(),
    )
    grouped = {
        (str(row["metric_key"]), str(row["status"])): int(row["total"])
        for row in (
            ConversationDeliveryPart.objects.unscoped()
            .filter(status__in=open_statuses)
            .annotate(metric_key=metric_key)
            .values("metric_key", "status")
            .annotate(total=Count("id"))
        )
    }
    known_keys = {
        DELIVERY_PART_KEY_BODY,
        DELIVERY_METRIC_PART_KEY_IMAGE,
        DELIVERY_PART_KEY_FALLBACK,
        *(part_key for part_key, _ in grouped),
    }
    # Always report body/image/fallback so a drained queue still publishes zeros.
    for part_key in sorted(known_keys):
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
        if _rolls_up_parent(part):
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
