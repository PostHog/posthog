import json
import datetime as dt
from dataclasses import dataclass
from uuid import UUID

from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExport, BatchExportRun
from posthog.batch_exports.service import afetch_batch_export_runs_in_range, aupdate_records_total_count
from posthog.batch_exports.sql import EVENT_COUNT_BY_INTERVAL
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

LOGGER = get_logger(__name__)


def datetime_to_str(dt_obj: dt.datetime) -> str:
    """Convert datetime to consistent string format"""
    return dt_obj.strftime("%Y-%m-%d %H:%M:%S")


def str_to_datetime(datetime_str: str) -> dt.datetime:
    """Convert string to datetime"""
    return dt.datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.UTC)


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
class EventCount:
    interval_start: str
    interval_end: str
    count: int


@activity.defn
async def get_clickhouse_event_counts(inputs: GetEventCountsInputs) -> list[EventCount]:
    """Get the total number of events for a given team over a set of time intervals from ClickHouse."""

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
            results.append(EventCount(interval_start=interval_start, interval_end=interval_end, count=int(count)))

        return results


@dataclass
class UpdateBatchExportRunsInputs:
    batch_export_id: UUID
    results: list[EventCount]


@activity.defn
async def update_batch_export_runs(inputs: UpdateBatchExportRunsInputs) -> int:
    """Update BatchExportRuns with the expected number of events."""

    bind_contextvars(batch_export_id=inputs.batch_export_id)
    logger = LOGGER.bind()

    total_rows_updated = 0
    async with Heartbeater():
        for result in inputs.results:
            total_rows_updated += await aupdate_records_total_count(
                batch_export_id=inputs.batch_export_id,
                interval_start=str_to_datetime(result.interval_start),
                interval_end=str_to_datetime(result.interval_end),
                count=result.count,
            )
    logger.info("Updated %s BatchExportRuns", total_rows_updated)
    return total_rows_updated


@dataclass
class FetchExportedEventCountsInputs:
    """Inputs for checking missing batch export runs"""

    batch_export_id: UUID
    overall_interval_start: str
    overall_interval_end: str
    interval: str


@activity.defn
async def fetch_exported_event_counts(inputs: FetchExportedEventCountsInputs) -> list[EventCount]:
    """Fetch the number of exported events (as recorded in our database) for a given batch export over a given interval.

    We assume that the interval is 5 minutes, as this is the only interval supported for monitoring at this time.
    """
    async with Heartbeater():
        # for simplicity, we assume that the interval is 5 minutes, as this is the only interval supported for monitoring at this time
        if inputs.interval != "every 5 minutes":
            raise NoValidBatchExportsFoundError(
                "Only intervals of 'every 5 minutes' are supported for monitoring at this time."
            )

        interval_start = str_to_datetime(inputs.overall_interval_start)
        interval_end = str_to_datetime(inputs.overall_interval_end)

        # Get all runs in the interval
        runs: list[BatchExportRun] = await afetch_batch_export_runs_in_range(
            batch_export_id=inputs.batch_export_id,
            interval_start=interval_start,
            interval_end=interval_end,
        )

        return [
            EventCount(
                interval_start=datetime_to_str(run.data_interval_start) if run.data_interval_start else "",
                interval_end=datetime_to_str(run.data_interval_end),
                count=run.records_completed or 0,
            )
            for run in runs
        ]


@dataclass
class ReconcileEventCountsInputs:
    """Inputs for reconciling event counts."""

    batch_export_id: UUID
    overall_interval_start: str
    overall_interval_end: str
    clickhouse_event_counts: list[EventCount]
    exported_event_counts: list[EventCount]


@activity.defn
async def reconcile_event_counts(inputs: ReconcileEventCountsInputs) -> None:
    """Reconcile the number of exported events with the number of events in ClickHouse.

    Log a warning if the number of exported events is lower than the number of events in ClickHouse.
    Also log a warning if we have any intervals for which we don't have any runs (this indicates that no run was
    scheduled in Temporal, which we've seen in the past during outages).
    These will subseqently trigger an alertmanager alert.
    """

    bind_contextvars(batch_export_id=inputs.batch_export_id)
    logger = LOGGER.bind()

    interval_start = str_to_datetime(inputs.overall_interval_start)
    interval_end = str_to_datetime(inputs.overall_interval_end)

    expected_intervals = _get_expected_intervals(interval_start, interval_end)

    missing_runs: list[tuple[dt.datetime, dt.datetime]] = []
    missing_events: list[EventCount] = []
    for start, end in expected_intervals:
        start_str = datetime_to_str(start)
        end_str = datetime_to_str(end)

        # event count in ClickHouse
        clickhouse_event_count = next(
            (
                count
                for count in inputs.clickhouse_event_counts
                if count.interval_start == start_str and count.interval_end == end_str
            ),
            None,
        )
        # exported event count
        exported_event_count = next(
            (
                count
                for count in inputs.exported_event_counts
                if count.interval_start == start_str and count.interval_end == end_str
            ),
            None,
        )

        if exported_event_count is None:
            missing_runs.append((start, end))
            continue

        if clickhouse_event_count is None:
            # it's possible that we don't have any events in ClickHouse for a given interval, but probably very rare for
            # the batch exports we monitor
            logger.info("No events in ClickHouse in interval %s to %s", start_str, end_str)
            continue

        if exported_event_count.count < clickhouse_event_count.count:
            missing_events.append(
                EventCount(
                    interval_start=start_str,
                    interval_end=end_str,
                    count=clickhouse_event_count.count - exported_event_count.count,
                )
            )

    if missing_runs:
        _log_warning_for_missing_batch_export_runs(inputs.batch_export_id, missing_runs)

    if missing_events:
        _log_warning_for_missing_events(inputs.batch_export_id, missing_events)


def _get_expected_intervals(
    interval_start: dt.datetime, interval_end: dt.datetime
) -> list[tuple[dt.datetime, dt.datetime]]:
    """
    Get the expected intervals (we can't rely on the intervals from the event count results as some could be missing,
    if we didn't schedule a batch export run or didn't have any events for a given interval).
    """
    expected_intervals = []
    current_interval_start = interval_start
    while current_interval_start < interval_end:
        expected_intervals.append((current_interval_start, current_interval_start + dt.timedelta(minutes=5)))
        current_interval_start += dt.timedelta(minutes=5)
    return expected_intervals


def _log_warning_for_missing_batch_export_runs(
    batch_export_id: UUID, missing_runs: list[tuple[dt.datetime, dt.datetime]]
):
    bind_contextvars(batch_export_id=batch_export_id)
    logger = LOGGER.bind()

    message = f"Batch Exports Monitoring: Found {len(missing_runs)} missing run(s):\n"
    for start, end in missing_runs:
        message += f"- Run {start} to {end}\n"

    logger.warning(message)


def _log_warning_for_missing_events(batch_export_id: UUID, missing_events: list[EventCount]):
    bind_contextvars(batch_export_id=batch_export_id)
    logger = LOGGER.bind()

    message = f"Batch Exports Monitoring: Found missing events:\n"
    for event in missing_events:
        message += f"- {event.count} events missing in interval {event.interval_start} to {event.interval_end}\n"

    logger.warning(message)


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

        bind_contextvars(batch_export_id=inputs.batch_export_id)
        logger = LOGGER.bind()
        logger.info("Starting batch exports monitoring workflow")

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
        interval_end_str = datetime_to_str(interval_end)
        interval_start_str = datetime_to_str(interval_start)

        clickhouse_event_counts = await workflow.execute_activity(
            get_clickhouse_event_counts,
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

        exported_event_counts = await workflow.execute_activity(
            fetch_exported_event_counts,
            FetchExportedEventCountsInputs(
                batch_export_id=batch_export_details.id,
                overall_interval_start=interval_start_str,
                overall_interval_end=interval_end_str,
                interval=batch_export_details.interval,
            ),
            start_to_close_timeout=dt.timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=dt.timedelta(seconds=20)),
            heartbeat_timeout=dt.timedelta(minutes=1),
        )

        await workflow.execute_activity(
            reconcile_event_counts,
            ReconcileEventCountsInputs(
                batch_export_id=batch_export_details.id,
                overall_interval_start=interval_start_str,
                overall_interval_end=interval_end_str,
                clickhouse_event_counts=clickhouse_event_counts,
                exported_event_counts=exported_event_counts,
            ),
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=dt.timedelta(seconds=20)),
            heartbeat_timeout=dt.timedelta(minutes=1),
        )

        return await workflow.execute_activity(
            update_batch_export_runs,
            UpdateBatchExportRunsInputs(batch_export_id=batch_export_details.id, results=clickhouse_event_counts),
            start_to_close_timeout=dt.timedelta(hours=1),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=dt.timedelta(seconds=20)),
            heartbeat_timeout=dt.timedelta(minutes=1),
        )
