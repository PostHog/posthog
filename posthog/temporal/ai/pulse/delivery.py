"""Delivery: persist findings to Postgres and emit CDP internal event + bell notifications."""

import dataclasses
from datetime import UTC, datetime
from typing import Any

from django.db import transaction

import structlog

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.exceptions_capture import capture_exception
from posthog.models import PulseDigest, PulseFinding, PulseSubscription
from posthog.models.activity_logging.activity_log import (
    ActivityContextBase,
    Detail,
    LogActivityEntry,
    bulk_log_activity,
)
from posthog.models.pulse import (
    PULSE_ACTIVITY_SCOPE,
    PULSE_ACTIVITY_VERB,
    PULSE_DIGEST_READY_EVENT,
    PulseDigestStatus,
    PulseFindingFeedback,
)
from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.pulse.types import EnrichedFinding

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class PulseActivityContext(ActivityContextBase):
    digest_id: str = ""
    metric_label: str = ""
    narrative: str = ""
    current_value: float = 0.0
    baseline_value: float = 0.0
    change_pct: float = 0.0
    z_score: float = 0.0
    attribution_breakdown: dict[str, Any] | None = None


def _emit_activity_log_entries(
    team_id: int, digest_id: str, findings_with_ids: list[tuple[str, EnrichedFinding]]
) -> None:
    """One ActivityLog row per finding so the side-panel bell picks it up. Bulk-inserted."""
    entries: list[LogActivityEntry] = [
        LogActivityEntry(
            organization_id=None,
            team_id=team_id,
            user=None,
            was_impersonated=False,
            item_id=finding_id,
            scope=PULSE_ACTIVITY_SCOPE,
            activity=PULSE_ACTIVITY_VERB,
            detail=Detail(
                name=finding.descriptor.label,
                context=PulseActivityContext(
                    digest_id=digest_id,
                    metric_label=finding.descriptor.label,
                    narrative=finding.narrative,
                    current_value=finding.current_value,
                    baseline_value=finding.baseline_value,
                    change_pct=finding.change_pct,
                    z_score=finding.z_score,
                    attribution_breakdown=finding.attribution_breakdown,
                ),
            ),
        )
        for finding_id, finding in findings_with_ids
    ]
    try:
        bulk_log_activity(entries)
    except Exception:
        logger.exception("pulse_activity_log_failed", team_id=team_id, digest_id=digest_id)


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


def _emit_internal_event(team_id: int, digest_id: str, findings: list[EnrichedFinding]) -> None:
    """Fire `$pulse_digest_ready` so CDP HogFunction destinations can route to Slack/email."""
    try:
        props = {
            "digest_id": digest_id,
            "finding_count": len(findings),
            "findings": [
                {
                    "metric": f.descriptor.label,
                    "narrative": f.narrative,
                    "current_value": f.current_value,
                    "baseline_value": f.baseline_value,
                    "change_pct": f.change_pct,
                    "z_score": f.z_score,
                    "attribution": f.attribution_breakdown,
                }
                for f in findings
            ],
        }
        produce_internal_event(
            team_id=team_id,
            event=InternalEventEvent(
                event=PULSE_DIGEST_READY_EVENT,
                distinct_id=f"team_{team_id}",
                properties=props,
            ),
        )
    except Exception as e:
        capture_exception(e, additional_properties={"feature": "pulse", "digest_id": digest_id})
        logger.exception("pulse_emit_internal_event_failed", team_id=team_id, digest_id=digest_id)


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
    """Persist findings and mark the digest DELIVERED. Notification fan-out is a separate step (workstream E)."""
    return await _persist_sync(team_id, digest_id, findings)
