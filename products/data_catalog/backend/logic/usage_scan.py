"""Start usage scans and close their snapshots.

A scan owns one snapshot row from start to finish. The row exists before the workflow starts, so
the caller can return it at once and the UI can show that a scan is computing.
"""

import asyncio
from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.utils import timezone

import structlog
import posthoganalytics
from temporalio.common import RetryPolicy

from posthog.models import Team
from posthog.temporal.common.client import sync_connect

from ..facade.contracts import SectionFailure, UsageSnapshotSummary
from ..facade.enums import USAGE_FLAG_KEY, UsageSnapshotStatus
from ..models import Metric, UsageSnapshot
from .usage_judge import JUDGE_MODEL
from .usage_snapshots import summary_of, write_payload_sections

logger = structlog.get_logger(__name__)

SCAN_WORKFLOW_NAME = "data-catalog-usage-scan"
DEFAULT_LOOKBACK_DAYS = 28

# A scan finishes within the workflow's 12-hour execution timeout. A row still computing after that
# belongs to a scan that died, and must not block the next one forever.
_STALE_COMPUTING = timedelta(hours=13)


class ScanAlreadyRunning(Exception):
    """The team has a scan in flight, so a second one would only race it."""


def create_usage_snapshot(team_id: int, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> UsageSnapshotSummary:
    now = timezone.now()
    snapshots = UsageSnapshot.objects.for_team(team_id)
    if snapshots.filter(status=UsageSnapshotStatus.COMPUTING.value, created_at__gt=now - _STALE_COMPUTING).exists():
        raise ScanAlreadyRunning()
    row = snapshots.create(
        team_id=team_id,
        status=UsageSnapshotStatus.COMPUTING.value,
        window_start=now - timedelta(days=lookback_days),
        window_end=now,
        judge_model=JUDGE_MODEL,
    )
    return summary_of(row)


def finalize_usage_snapshot(
    team_id: int, snapshot_id: UUID, error: str | None = None, failed_sections: Sequence[SectionFailure] = ()
) -> None:
    """Close the scan. A scan with some failed sections is done, and the payload names those sections."""
    if failed_sections:
        write_payload_sections(team_id, snapshot_id, failed_sections=list(failed_sections))
    UsageSnapshot.objects.for_team(team_id).filter(id=snapshot_id).update(
        status=(UsageSnapshotStatus.ERROR if error else UsageSnapshotStatus.DONE).value,
        error_message=error or "",
        computed_at=timezone.now(),
    )


def start_usage_scan(team: Team, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> UsageSnapshotSummary:
    """Create the snapshot row and start the scan workflow for it."""
    snapshot = create_usage_snapshot(team.id, lookback_days)
    try:
        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                SCAN_WORKFLOW_NAME,
                # A dict rather than the workflow's input class, because importing the temporal
                # package from here would import this module back through the activities.
                {"team_id": team.id, "snapshot_id": str(snapshot.id)},
                id=scan_workflow_id(snapshot.id),
                task_queue=settings.WEEKLY_DIGEST_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        )
    except Exception as error:
        # The row is already committed, so leaving it would show a scan computing with no workflow
        # behind it until it goes stale.
        finalize_usage_snapshot(team.id, snapshot.id, error=f"The scan could not start: {error}")
        raise
    return snapshot


def scan_workflow_id(snapshot_id: UUID) -> str:
    return f"{SCAN_WORKFLOW_NAME}-{snapshot_id}"


def teams_due_for_scan() -> list[int]:
    """Teams with at least one live metric and the usage flag on, in id order."""
    team_ids = sorted(set(Metric.objects.unscoped().filter(deleted=False).values_list("team_id", flat=True)))
    return [team.id for team in Team.objects.filter(id__in=team_ids).order_by("id") if _flag_on_for_team(team)]


def _flag_on_for_team(team: Team) -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                USAGE_FLAG_KEY,
                f"team_{team.id}",
                groups={"organization": str(team.organization_id), "project": str(team.uuid)},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as error:
        logger.warning("data_catalog_usage_flag_eval_failed", team_id=team.id, error=str(error))
        return False
