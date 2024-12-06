import datetime as dt
import json
from dataclasses import dataclass
from uuid import UUID

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import (
    aget_active_event_batch_exports,
    aupdate_expected_records_count,
)
from posthog.batch_exports.sql import EVENT_COUNT_BY_INTERVAL
from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client


class NoActiveBatchExportsFoundError(Exception):
    """Exception raised when no active events batch exports are found for a given team."""

    def __init__(self, team_id: int):
        super().__init__(f"No active events batch exports found for team {team_id}")


class NoValidBatchExportsFoundError(Exception):
    """Exception raised when no valid events batch exports are found for a given team."""

    def __init__(self, message: str = "No valid events batch exports found for team"):
        super().__init__(message)


@dataclass
class BatchExportMonitoringInputs:
    """Inputs for the BatchExportMonitoringWorkflow.

    Attributes:
        team_id: The team id to monitor batch exports for.
    """

    # TODO - make this a list of team ids or single?
    # or maybe a (list of) batch export id(s) instead?
    team_id: int


@dataclass
class BatchExportDetails:
    id: UUID
    interval: str
    exclude_events: list[str]
    include_events: list[str]


@activity.defn
async def get_batch_export(team_id: int) -> BatchExportDetails:
    """Get the number of records completed for a given team."""
    models = await aget_active_event_batch_exports(team_id)
    if len(models) == 0:
        raise NoActiveBatchExportsFoundError(team_id)
    if len(models) > 1:
        activity.logger.warning("More than one active events batch export found; using first one...")
    model = models[0]
    if model.interval_time_delta != dt.timedelta(minutes=5):
        raise NoValidBatchExportsFoundError(
            "Only batch exports with interval of 5 minutes are supported for monitoring at this time."
        )
    config = model.destination.config
    return BatchExportDetails(
        id=model.id,
        interval=model.interval,
        exclude_events=config.get("exclude_events", []),
        include_events=config.get("include_events", []),
    )


@dataclass
class GetEventCountsInputs:
    team_id: int
    interval: str
    overall_interval_start: str
    overall_interval_end: str
    exclude_events: list[str]
    include_events: list[str]


@dataclass
class EventCountsOutput:
    interval_start: str
    interval_end: str
    count: int


@dataclass
class GetEventCountsOutputs:
    results: list[EventCountsOutput]


@activity.defn
async def get_event_counts(inputs: GetEventCountsInputs) -> GetEventCountsOutputs:
    """Get the total number of events for a given team over a set of time intervals."""

    query = EVENT_COUNT_BY_INTERVAL

    interval = inputs.interval
    # we check interval is "every 5 minutes" above but double check here
    if not interval.startswith("every 5 minutes"):
        raise NoValidBatchExportsFoundError(
            "Only intervals of 'every 5 minutes' are supported for monitoring at this time."
        )
    _, value, unit = interval.split(" ")
    interval = f"{value} {unit}"

    query_params = {
        "team_id": inputs.team_id,
        "interval": interval,
        "overall_interval_start": inputs.overall_interval_start,
        "overall_interval_end": inputs.overall_interval_end,
        "include_events": inputs.include_events,
        "exclude_events": inputs.exclude_events,
    }
    async with get_client() as client:
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        response = await client.read_query(query, query_params)
        results = []
        for line in response.decode("utf-8").splitlines():
            interval_start, interval_end, count = line.strip().split("\t")
            results.append(
                EventCountsOutput(interval_start=interval_start, interval_end=interval_end, count=int(count))
            )

        return GetEventCountsOutputs(results=results)


@dataclass
class UpdateBatchExportRunsInputs:
    batch_export_id: UUID
    results: list[EventCountsOutput]


@activity.defn
async def update_batch_export_runs(inputs: UpdateBatchExportRunsInputs) -> int:
    """Update BatchExportRuns with the expected number of events."""

    total_rows_updated = 0
    for result in inputs.results:
        total_rows_updated += await aupdate_expected_records_count(
            batch_export_id=inputs.batch_export_id,
            interval_start=dt.datetime.strptime(result.interval_start, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.UTC),
            interval_end=dt.datetime.strptime(result.interval_end, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.UTC),
            count=result.count,
        )
    activity.logger.info(f"Updated {total_rows_updated} BatchExportRuns")
    return total_rows_updated


@workflow.defn(name="batch-export-monitoring")
class BatchExportMonitoringWorkflow(PostHogWorkflow):
    """Workflow to monitor batch exports.

    We have had some issues with batch exports in the past, where some events
    have been missing. The purpose of this workflow is to monitor the status of
    batch exports for a given customer by reconciling the number of exported
    events with the number of events in ClickHouse for a given interval.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BatchExportMonitoringInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return BatchExportMonitoringInputs(**loaded)

    @workflow.run
    async def run(self, inputs: BatchExportMonitoringInputs):
        """Workflow implementation to monitor batch exports for a given team."""
        # TODO - check if this is the right way to do logging since there seems to be a few different ways
        workflow.logger.info("Starting batch exports monitoring workflow for team %s", inputs.team_id)

        batch_export_details = await workflow.execute_activity(
            get_batch_export,
            inputs.team_id,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=dt.timedelta(seconds=20),
                non_retryable_error_types=["NoActiveBatchExportsFoundError"],
            ),
            heartbeat_timeout=dt.timedelta(minutes=1),
        )

        # time interval to check is not the previous hour but the hour before that
        # (just to ensure all recent batch exports have run successfully)
        now = dt.datetime.now(tz=dt.UTC)
        interval_end = now.replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=1)
        interval_start = interval_end - dt.timedelta(hours=1)
        interval_end_str = interval_end.strftime("%Y-%m-%d %H:%M:%S")
        interval_start_str = interval_start.strftime("%Y-%m-%d %H:%M:%S")

        total_events = await workflow.execute_activity(
            get_event_counts,
            GetEventCountsInputs(
                team_id=inputs.team_id,
                interval=batch_export_details.interval,
                overall_interval_start=interval_start_str,
                overall_interval_end=interval_end_str,
                exclude_events=batch_export_details.exclude_events,
                include_events=batch_export_details.include_events,
            ),
            start_to_close_timeout=dt.timedelta(hours=1),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=dt.timedelta(seconds=20)),
            heartbeat_timeout=dt.timedelta(minutes=1),
        )

        return await workflow.execute_activity(
            update_batch_export_runs,
            UpdateBatchExportRunsInputs(batch_export_id=batch_export_details.id, results=total_events.results),
            start_to_close_timeout=dt.timedelta(hours=1),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=dt.timedelta(seconds=20)),
            heartbeat_timeout=dt.timedelta(minutes=1),
        )
