import uuid

from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.sync import database_sync_to_async

from ...facade.contracts import SectionFailure
from ...facade.enums import UsageSection
from ...logic.usage_adjusted import detect_adjusted_runs_into_snapshot
from ...logic.usage_runs import collect_metric_runs_into_snapshot
from ...logic.usage_scan import ScanAlreadyRunning, create_usage_snapshot, finalize_usage_snapshot, teams_due_for_scan
from ...logic.usage_topics import collect_topics_into_snapshot
from ...logic.usage_uncovered import find_uncovered_into_snapshot
from .types import CreateSnapshotInput, FinalizeSnapshotInput, ScanStepInput, SectionWritten


@activity.defn(name="data-catalog-usage-collect-metric-runs")
async def collect_metric_runs(input: ScanStepInput) -> SectionWritten:
    rows = await database_sync_to_async(collect_metric_runs_into_snapshot, thread_sensitive=False)(
        team_id=input.team_id, snapshot_id=input.snapshot_id, telemetry_team_id=input.telemetry_team_id
    )
    return SectionWritten(rows=rows)


@activity.defn(name="data-catalog-usage-detect-adjusted-runs")
async def detect_adjusted_runs(input: ScanStepInput) -> SectionWritten:
    rows = await detect_adjusted_runs_into_snapshot(
        team_id=input.team_id,
        snapshot_id=input.snapshot_id,
        telemetry_team_id=input.telemetry_team_id,
        heartbeat=activity.heartbeat,
    )
    return SectionWritten(rows=rows)


@activity.defn(name="data-catalog-usage-collect-topics")
async def collect_topics(input: ScanStepInput) -> SectionWritten:
    rows = await collect_topics_into_snapshot(
        team_id=input.team_id,
        snapshot_id=input.snapshot_id,
        telemetry_team_id=input.telemetry_team_id,
        heartbeat=activity.heartbeat,
    )
    return SectionWritten(rows=rows)


@activity.defn(name="data-catalog-usage-find-uncovered")
async def find_uncovered(input: ScanStepInput) -> SectionWritten:
    rows = await find_uncovered_into_snapshot(
        team_id=input.team_id,
        snapshot_id=input.snapshot_id,
        telemetry_team_id=input.telemetry_team_id,
        heartbeat=activity.heartbeat,
    )
    return SectionWritten(rows=rows)


@activity.defn(name="data-catalog-usage-list-teams")
async def list_teams_due() -> list[int]:
    return await database_sync_to_async(teams_due_for_scan, thread_sensitive=False)()


@activity.defn(name="data-catalog-usage-create-snapshot")
async def create_snapshot(input: CreateSnapshotInput) -> uuid.UUID:
    try:
        snapshot = await database_sync_to_async(create_usage_snapshot, thread_sensitive=False)(
            input.team_id, input.lookback_days
        )
    except ScanAlreadyRunning:
        raise ApplicationError("A usage scan is already running for this team.", non_retryable=True)
    return snapshot.id


@activity.defn(name="data-catalog-usage-finalize-snapshot")
async def finalize_snapshot(input: FinalizeSnapshotInput) -> None:
    failures = [
        SectionFailure(section=UsageSection(step.section), reason=step.reason) for step in input.failed_sections
    ]
    await database_sync_to_async(finalize_usage_snapshot, thread_sensitive=False)(
        input.team_id, input.snapshot_id, error=input.error, failed_sections=failures
    )
