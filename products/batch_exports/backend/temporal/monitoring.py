import datetime as dt
import json
from dataclasses import dataclass
from uuid import UUID

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExport
from posthog.batch_exports.service import (
    afetch_batch_export_runs_in_range,
    aupdate_records_total_count,
)
from posthog.batch_exports.sql import EVENT_COUNT_BY_INTERVAL
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater


class BatchExportNotFoundError(Exception):
    """Exception raised when batch export is not found."""

    def __init__(self, batch_export_id: UUID):
        super().__init__(f"Batch export with id {batch_export_id} not found")


class NoValidBatchExportsFoundError(Exception):
    """Exception raised when no valid batch export is found."""

    def __init__(self, message: str = "No valid batch exports found"):
        super().__init__(message)


@dataclass
class BatchExportMonitoringInputs:
    """Inputs for the BatchExportMonitoringWorkflow.

    Attributes:
        batch_export_id: The batch export id to monitor.
    """

    batch_export_id: UUID


@dataclass
class BatchExportDetails:
    id: UUID
    team_id: int
    interval: str
    exclude_events: list[str]
    include_events: list[str]


@activity.defn
async def get_batch_export(batch_export_id: UUID) -> BatchExportDetails:
    """Fetch a batch export from the database and return its details."""
    batch_export = (
        await BatchExport.objects.filter(id=batch_export_id, model="events", paused=False, deleted=False)
        .prefetch_related("destination")
        .afirst()
    )
    if batch_export is None:
        raise BatchExportNotFoundError(batch_export_id)
    if batch_export.deleted is True:
        raise NoValidBatchExportsFoundError("Batch export has been deleted")
    if batch_export.paused is True:
        raise NoValidBatchExportsFoundError("Batch export is paused")
    if batch_export.model != "events":
        raise NoValidBatchExportsFoundError("Batch export model is not 'events'")
    if batch_export.interval_time_delta != dt.timedelta(minutes=5):
        raise NoValidBatchExportsFoundError(
            "Only batch exports with interval of 5 minutes are supported for monitoring at this time."
        )
    config = batch_export.destination.config
    return BatchExportDetails(
        id=batch_export.id,
        team_id=batch_export.team_id,
        interval=batch_export.interval,
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
    async with Heartbeater(), get_client() as client:
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
    async with Heartbeater():
        for result in inputs.results:
            total_rows_updated += await aupdate_records_total_count(
                batch_export_id=inputs.batch_export_id,
                interval_start=dt.datetime.strptime(result.interval_start, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.UTC),
                interval_end=dt.datetime.strptime(result.interval_end, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.UTC),
                count=result.count,
            )
    activity.logger.info(f"Updated {total_rows_updated} BatchExportRuns")
    return total_rows_updated


@dataclass
class CheckForMissingBatchExportRunsInputs:
    """Inputs for checking missing batch export runs"""

    batch_export_id: UUID
    overall_interval_start: str
    overall_interval_end: str
    interval: str


def _log_warning_for_missing_batch_export_runs(
    batch_export_id: UUID, missing_runs: list[tuple[dt.datetime, dt.datetime]]
):
    message = (
        f"Batch Exports Monitoring: Found {len(missing_runs)} missing run(s) for batch export {batch_export_id}:\n"
    )
    for start, end in missing_runs:
        message += f"- Run {start.strftime('%Y-%m-%d %H:%M:%S')} to {end.strftime('%Y-%m-%d %H:%M:%S')}\n"

    activity.logger.warning(message)


@activity.defn
async def check_for_missing_batch_export_runs(inputs: CheckForMissingBatchExportRunsInputs) -> int:
    """Check for missing batch export runs and log a warning if any are found.
    (We can then alert based on these log entries)

    Returns:
        The number of missing batch export runs found.
    """
    async with Heartbeater():
        interval_start = dt.datetime.strptime(inputs.overall_interval_start, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.UTC)
        interval_end = dt.datetime.strptime(inputs.overall_interval_end, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.UTC)
        # Get all runs in the interval
        runs = await afetch_batch_export_runs_in_range(
            batch_export_id=inputs.batch_export_id,
            interval_start=interval_start,
            interval_end=interval_end,
        )

        # for simplicity, we assume that the interval is 5 minutes, as this is the only interval supported for monitoring at this time
        if inputs.interval != "every 5 minutes":
            raise NoValidBatchExportsFoundError(
                "Only intervals of 'every 5 minutes' are supported for monitoring at this time."
            )
        expected_run_intervals: list[tuple[dt.datetime, dt.datetime]] = []
        current_run_start_interval = interval_start
        while current_run_start_interval < interval_end:
            expected_run_intervals.append(
                (current_run_start_interval, current_run_start_interval + dt.timedelta(minutes=5))
            )
            current_run_start_interval += dt.timedelta(minutes=5)

        missing_runs: list[tuple[dt.datetime, dt.datetime]] = []
        for start, end in expected_run_intervals:
            if start not in [run.data_interval_start for run in runs]:
                missing_runs.append((start, end))

        if missing_runs:
            _log_warning_for_missing_batch_export_runs(inputs.batch_export_id, missing_runs)

        return len(missing_runs)


@workflow.defn(name="batch-export-monitoring")
class BatchExportMonitoringWorkflow(PostHogWorkflow):
    """Workflow to monitor batch exports.

    We have had some issues with batch exports in the past, where some events
    have been missing. The purpose of this workflow is to monitor the status of
    a given batch export by:
    1. Checking for missing batch export runs (we've had an incident in the past
        where Temporal has not scheduled a workflow for a particular time interval
        for some reason).
    2. Reconciling the number of exported events with the number of events in
        ClickHouse for a given interval.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BatchExportMonitoringInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return BatchExportMonitoringInputs(**loaded)

    @workflow.run
    async def run(self, inputs: BatchExportMonitoringInputs):
        """Workflow implementation to monitor a given batch export."""
        workflow.logger.info(
            "Starting batch exports monitoring workflow for batch export id %s", inputs.batch_export_id
        )

        batch_export_details = await workflow.execute_activity(
            get_batch_export,
            inputs.batch_export_id,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=20),
                non_retryable_error_types=["BatchExportNotFoundError", "NoValidBatchExportsFoundError"],
            ),
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
                team_id=batch_export_details.team_id,
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

        await workflow.execute_activity(
            check_for_missing_batch_export_runs,
            CheckForMissingBatchExportRunsInputs(
                batch_export_id=batch_export_details.id,
                overall_interval_start=interval_start_str,
                overall_interval_end=interval_end_str,
                interval=batch_export_details.interval,
            ),
            start_to_close_timeout=dt.timedelta(minutes=10),
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
