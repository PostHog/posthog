from temporalio import activity

from posthog.sync import database_sync_to_async

from ...logic.usage_adjusted import detect_adjusted_runs_into_snapshot
from ...logic.usage_runs import collect_metric_runs_into_snapshot
from .types import CollectRunsInput, DetectAdjustedRunsInput, SectionWritten


@activity.defn(name="data-catalog-usage-collect-metric-runs")
async def collect_metric_runs(input: CollectRunsInput) -> SectionWritten:
    rows = await database_sync_to_async(collect_metric_runs_into_snapshot, thread_sensitive=False)(
        team_id=input.team_id, snapshot_id=input.snapshot_id, telemetry_team_id=input.telemetry_team_id
    )
    return SectionWritten(rows=rows)


@activity.defn(name="data-catalog-usage-detect-adjusted-runs")
async def detect_adjusted_runs(input: DetectAdjustedRunsInput) -> SectionWritten:
    rows = await detect_adjusted_runs_into_snapshot(
        team_id=input.team_id,
        snapshot_id=input.snapshot_id,
        telemetry_team_id=input.telemetry_team_id,
        heartbeat=activity.heartbeat,
    )
    return SectionWritten(rows=rows)
