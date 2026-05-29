"""Delivery: persist findings to Postgres, then fan out one in-app notification per team member."""

from datetime import UTC, datetime

from django.db import transaction

import structlog

from posthog.models import OrganizationMembership, PulseDigest, PulseFinding, PulseSubscription, Team
from posthog.models.pulse import PulseDigestStatus, PulseFindingFeedback
from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.pulse.types import EnrichedFinding

logger = structlog.get_logger(__name__)


def _persist_findings_sync(
    digest_id: str, team_id: int, findings: list[EnrichedFinding]
) -> list[tuple[str, EnrichedFinding]]:
    """Persist findings once. Returns (finding_id, finding) pairs. Idempotent:
    short-circuits if the digest is already DELIVERED or already has findings."""
    with team_scope(team_id, canonical=True):
        digest = PulseDigest.objects.get(id=digest_id, team_id=team_id)

        existing = list(PulseFinding.objects.filter(digest_id=digest_id).order_by("rank"))
        if digest.status == PulseDigestStatus.DELIVERED or existing:
            return [(str(row.id), f) for row, f in zip(existing, findings)]

        rows = [
            PulseFinding(
                team_id=team_id,  # denormalized from the digest so the row is fail-closed
                digest=digest,
                metric_descriptor=f.descriptor.model_dump(),
                metric_label=f.descriptor.label[:255],
                current_value=f.current_value,
                baseline_value=f.baseline_value,
                change_pct=f.change_pct,
                impact=f.impact,
                robust_z=f.robust_z,
                attribution_breakdown=f.attribution_breakdown,
                narrative=f.narrative,
                feedback=PulseFindingFeedback.PENDING,
                rank=idx,
            )
            for idx, f in enumerate(findings)
        ]
        created = PulseFinding.objects.bulk_create(rows)

        digest.status = PulseDigestStatus.DELIVERED
        digest.save(update_fields=["status"])

        return [(str(row.id), f) for row, f in zip(created, findings)]


def _pulse_notification_title(findings: list[EnrichedFinding]) -> str:
    top = findings[0]
    direction = "up" if top.change_pct > 0 else "down"
    headline = f"{top.descriptor.label} is {direction} {abs(top.change_pct):.0%}"
    if len(findings) > 1:
        headline += f" (+{len(findings) - 1} more)"
    return headline[:255]


def _dispatch_pulse_notifications(team_id: int, digest_id: str, findings: list[EnrichedFinding]) -> None:
    """Fan out one in-app notification per team member for a delivered digest.

    Idempotent: a Temporal retry that re-enters delivery re-checks has_been_dispatched
    per recipient (keyed on digest_id) and skips anyone already notified.
    """
    # Lazy import: the pulse package is eagerly preloaded via posthog.api, and importing the
    # notifications facade at module level triggers an app-init circular import. It resolves
    # fine at activity-call time, matching the pattern in selection.py.
    from products.notifications.backend.facade.api import (
        NotificationData,
        NotificationType,
        Priority,
        SourceType,
        TargetType,
        create_notification,
        has_been_dispatched,
    )

    if not findings:
        return

    title = _pulse_notification_title(findings)
    body = findings[0].narrative
    source_url = f"/pulse?digest={digest_id}"
    organization_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return
    member_ids = OrganizationMembership.objects.filter(organization_id=organization_id).values_list(
        "user_id", flat=True
    )
    for user_id in member_ids:
        if has_been_dispatched(
            notification_type=NotificationType.PULSE_DIGEST,
            target_type=TargetType.USER,
            target_id=str(user_id),
            resource_id=digest_id,
            source_id=digest_id,
        ):
            continue
        create_notification(
            NotificationData(
                team_id=team_id,
                notification_type=NotificationType.PULSE_DIGEST,
                priority=Priority.NORMAL,
                title=title,
                body=body,
                target_type=TargetType.USER,
                target_id=str(user_id),
                resource_id=digest_id,
                source_url=source_url,
                source_type=SourceType.PULSE,
                source_id=digest_id,
            )
        )


def _update_subscription_timestamps_sync(team_id: int) -> None:
    with team_scope(team_id, canonical=True):
        subscription = PulseSubscription.objects.filter(team_id=team_id).first()
        if subscription:
            subscription.last_scan_at = datetime.now(UTC)
            subscription.save(update_fields=["last_scan_at"])


@database_sync_to_async
def _persist_sync(team_id: int, digest_id: str, findings: list[EnrichedFinding]) -> list[str]:
    with transaction.atomic():
        findings_with_ids = _persist_findings_sync(digest_id, team_id, findings)
        _update_subscription_timestamps_sync(team_id)
    return [finding_id for finding_id, _ in findings_with_ids]


async def persist_findings(team_id: int, digest_id: str, findings: list[EnrichedFinding]) -> list[str]:
    """Persist findings and mark the digest DELIVERED. Notification fan-out is a separate step."""
    return await _persist_sync(team_id, digest_id, findings)


async def notify_digest(team_id: int, digest_id: str, findings: list[EnrichedFinding]) -> None:
    """Fan out in-app notifications for a delivered digest.

    Runs after persist_findings so a rolled-back persist never produces orphan notifications.
    create_notification defers the Kafka publish to on_commit, so the row write and the
    notification stay consistent.
    """
    await database_sync_to_async(_dispatch_pulse_notifications)(team_id, digest_id, findings)
