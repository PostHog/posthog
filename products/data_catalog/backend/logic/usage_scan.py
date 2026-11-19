"""Start usage scans and close their snapshots.

A scan owns one snapshot row from start to finish. The row exists before the workflow starts, so
the caller can return it at once and the UI can show that a scan is computing.
"""

import asyncio
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

import structlog
import posthoganalytics
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.service import RPCError, RPCStatusCode

from posthog.models import Team
from posthog.models.utils import uuid7
from posthog.temporal.common.client import sync_connect

from ..facade.contracts import SectionFailure, UsageSnapshotSummary
from ..facade.enums import USAGE_FLAG_KEY, UsageSnapshotStatus
from ..models import Metric, UsageSnapshot
from .usage_judge import JUDGE_MODEL, require_ai_consent
from .usage_snapshots import (
    SCAN_EXECUTION_TIMEOUT,
    SCAN_STOPPED_MESSAGE,
    STALE_COMPUTING,
    summary_of,
    usage_scans_supported,
    write_payload_sections,
)

logger = structlog.get_logger(__name__)

SCAN_WORKFLOW_NAME = "data-catalog-usage-scan"
DEFAULT_LOOKBACK_DAYS = 28
# Every scan spends model calls, and session requests skip the default API throttles.
RECOMPUTE_COOLDOWN = timedelta(hours=1)
_FLAG_CONCURRENCY = 8
SCAN_START_FAILED_MESSAGE = "The scan could not start."


class ScanAlreadyRunning(Exception):
    """The team has a scan in flight, so a second one would only race it."""


class ScanCooldown(Exception):
    """The team started a scan less than an hour ago."""


def create_usage_snapshot(
    team_id: int,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    snapshot_id: UUID | None = None,
    cooldown: timedelta | None = None,
) -> UsageSnapshotSummary:
    """Create the computing row for a new scan.

    With a ``snapshot_id``, a second call returns the row the first call made, so an activity retry
    after a lost reply does not fail on its own row.
    """
    require_ai_consent(Team.objects.select_related("organization").get(id=team_id))
    now = timezone.now()
    snapshots = UsageSnapshot.objects.for_team(team_id)
    if snapshot_id is not None and (existing := snapshots.filter(id=snapshot_id).first()) is not None:
        return summary_of(existing)
    if cooldown is not None:
        # A scan that never started used no compute, so it does not hold back the next one.
        recent = list(
            snapshots.filter(created_at__gte=now - cooldown)
            .exclude(status=UsageSnapshotStatus.ERROR.value, error_message=SCAN_START_FAILED_MESSAGE)
            .values_list("status", flat=True)
        )
        if UsageSnapshotStatus.COMPUTING.value in recent:
            raise ScanAlreadyRunning()
        if recent:
            raise ScanCooldown()
    # The unique constraint allows one computing row per team, so a dead scan's row must close first.
    snapshots.filter(status=UsageSnapshotStatus.COMPUTING.value, created_at__lte=now - STALE_COMPUTING).update(
        status=UsageSnapshotStatus.ERROR.value, error_message=SCAN_STOPPED_MESSAGE, computed_at=now
    )
    try:
        with transaction.atomic():
            row = snapshots.create(
                id=snapshot_id or uuid7(),
                team_id=team_id,
                status=UsageSnapshotStatus.COMPUTING.value,
                window_start=now - timedelta(days=lookback_days),
                window_end=now,
                judge_model=JUDGE_MODEL,
            )
    except IntegrityError as error:
        raise ScanAlreadyRunning() from error
    return summary_of(row)


def finalize_usage_snapshot(
    team_id: int, snapshot_id: UUID, error: str | None = None, failed_sections: Sequence[SectionFailure] = ()
) -> None:
    """Close the scan. A scan with some failed sections is done, and the payload names those sections."""
    if failed_sections:
        try:
            write_payload_sections(team_id, snapshot_id, failed_sections=list(failed_sections))
        except UsageSnapshot.DoesNotExist:
            # A team deleted during the scan takes its row with it, so nothing is left to close.
            return
    # Only a computing row closes, so a late close after a failed child keeps the scan's own error.
    UsageSnapshot.objects.for_team(team_id).filter(id=snapshot_id, status=UsageSnapshotStatus.COMPUTING.value).update(
        status=(UsageSnapshotStatus.ERROR if error else UsageSnapshotStatus.DONE).value,
        error_message=error or "",
        computed_at=timezone.now(),
    )


def start_usage_scan(team: Team, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> UsageSnapshotSummary:
    """Create the snapshot row and start the scan workflow for it."""
    # The temporal package imports this module through its activities, so a module-level import is a cycle.
    from ..temporal.usage_scan.types import UsageScanInput  # noqa: PLC0415

    snapshot = create_usage_snapshot(team.id, lookback_days, cooldown=RECOMPUTE_COOLDOWN)
    workflow_id = scan_workflow_id(snapshot.id)
    client: Client | None = None
    try:
        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                SCAN_WORKFLOW_NAME,
                UsageScanInput(team_id=team.id, snapshot_id=snapshot.id),
                id=workflow_id,
                task_queue=settings.WEEKLY_DIGEST_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=SCAN_EXECUTION_TIMEOUT,
            )
        )
    except Exception:
        logger.exception("data_catalog_usage_scan_start_failed", team_id=team.id, snapshot_id=str(snapshot.id))
        # The row is already committed, so leaving it would show a scan computing with no workflow
        # behind it until it goes stale. A lost reply can still hide a started workflow, which
        # closes the row itself.
        if client is None or not _workflow_exists(client, workflow_id):
            finalize_usage_snapshot(team.id, snapshot.id, error=SCAN_START_FAILED_MESSAGE)
        raise
    return snapshot


def _workflow_exists(client: Client, workflow_id: str) -> bool:
    try:
        asyncio.run(client.get_workflow_handle(workflow_id).describe())
    except Exception as error:
        if isinstance(error, RPCError) and error.status == RPCStatusCode.NOT_FOUND:
            return False
        logger.warning("data_catalog_usage_scan_describe_failed", workflow_id=workflow_id, error=str(error))
    # When the check itself fails, the row stays computing. It goes stale if no workflow runs.
    return True


def scan_workflow_id(snapshot_id: UUID) -> str:
    return f"{SCAN_WORKFLOW_NAME}-{snapshot_id}"


def teams_due_for_scan() -> list[int]:
    """Teams with at least one live metric, AI data processing approved, and the usage flag on, in id order."""
    if not usage_scans_supported():
        return []
    flagged = teams_with_metrics_and_flag(USAGE_FLAG_KEY)
    return list(
        Team.objects.filter(id__in=flagged, organization__is_ai_data_processing_approved=True)
        .order_by("id")
        .values_list("id", flat=True)
    )


def teams_with_metrics_and_flag(flag_key: str) -> list[int]:
    """Teams with at least one live metric and the flag on, in id order."""
    teams_with_metrics = Metric.objects.unscoped().filter(deleted=False).values("team_id")
    teams = list(Team.objects.filter(id__in=teams_with_metrics).order_by("id"))
    # Each check can be a remote flag evaluation, so a long serial loop would outlast the activity.
    with ThreadPoolExecutor(max_workers=_FLAG_CONCURRENCY) as pool:
        flags = list(pool.map(lambda team: _flag_on_for_team(team, flag_key), teams))
    return [team.id for team, on in zip(teams, flags, strict=True) if on]


def _flag_on_for_team(team: Team, flag_key: str) -> bool:
    # The weekly run has no user, so it checks the flag with a stand-in distinct id. A condition on
    # people never matches that id, so each scan flag must target organizations or projects only.
    try:
        return bool(
            posthoganalytics.feature_enabled(
                flag_key,
                f"team_{team.id}",
                groups={"organization": str(team.organization_id), "project": str(team.uuid)},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as error:
        logger.warning("data_catalog_usage_flag_eval_failed", team_id=team.id, flag_key=flag_key, error=str(error))
        return False
