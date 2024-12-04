import datetime as dt
import json
from dataclasses import dataclass

from django.db.models import Max, Sum
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import aget_active_event_batch_exports
from posthog.batch_exports.sql import EVENT_COUNT_FROM_UNBOUNDED_VIEW
from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import get_client


class NoActiveBatchExportsFoundError(Exception):
    """Exception raised when no active events batch exports are found for a given team."""

    def __init__(self, team_id: int):
        super().__init__(f"No active events batch exports found for team {team_id}")


@dataclass
class BatchExportMonitoringInputs:
    """Inputs for the BatchExportMonitoringWorkflow.

    Attributes:
        team_id: The team id to monitor batch exports for.
    """

    # TODO - make this a list of team ids or single?
    team_id: int


@dataclass
class BatchExportDetails:
    id: str
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
    config = model.destination.config
    return BatchExportDetails(
        id=model.id, exclude_events=config.get("exclude_events", []), include_events=config.get("include_events", [])
    )


@dataclass
class GetRecordsCompletedInputs:
    batch_export_id: str
    interval_start: str
    interval_end: str


@activity.defn
async def get_records_completed(inputs: GetRecordsCompletedInputs) -> int:
    """Get the number of records completed for the given batch export and interval.

    There will typically be multiple batch export runs for a given batch export,
    each with a different data interval, so we need to sum these. In addition, a
    particular batch export run could have been re-run multiple times (eg
    manually by the user), so we need to dedupe these (we choose to take the one
    with the highest records_completed).
    """

    deduped_batch_export_runs = (
        BatchExportRun.objects.filter(
            batch_export_id=inputs.batch_export_id,
            data_interval_start__gte=inputs.interval_start,
            data_interval_start__lt=inputs.interval_end,
        )
        .values("data_interval_start")
        .annotate(max_records_completed=Max("records_completed"))
    )

    result = await deduped_batch_export_runs.aaggregate(records_sum=Sum("max_records_completed"))
    return result["records_sum"] or 0


@dataclass
class GetEventsCountInputs:
    team_id: int
    interval_start: str
    interval_end: str
    exclude_events: list[str]
    include_events: list[str]


@activity.defn
async def get_events_count(inputs: GetEventsCountInputs) -> int:
    """Get the total number of events for a given team and time interval."""

    # TODO: is this the best query to use?
    query = EVENT_COUNT_FROM_UNBOUNDED_VIEW
    query_params = {
        "team_id": inputs.team_id,
        "interval_start": inputs.interval_start,
        "interval_end": inputs.interval_end,
        "include_events": inputs.include_events,
        "exclude_events": inputs.exclude_events,
    }
    async with get_client() as client:
        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        response = await client.read_query(query, query_params)
        line = response.decode("utf-8").splitlines()[0]
        count_str = line.strip()
        return int(count_str)


@dataclass
class CompareCountsInputs:
    total_completed_records: int
    total_events: int


@activity.defn
async def compare_counts(inputs: CompareCountsInputs) -> bool:
    """Compare the number of events in ClickHouse with the reported number of exported events."""
    # for now, return True if within 10% of each other
    if inputs.total_events == 0:
        return inputs.total_completed_records == 0
    abs_diff = abs(inputs.total_completed_records - inputs.total_events)
    return abs_diff / inputs.total_events < 0.1


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

        total_completed_records = await workflow.execute_activity(
            get_records_completed,
            GetRecordsCompletedInputs(
                batch_export_id=batch_export_details.id,
                interval_start=interval_start_str,
                interval_end=interval_end_str,
            ),
            start_to_close_timeout=dt.timedelta(hours=1),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=dt.timedelta(seconds=20)),
            heartbeat_timeout=dt.timedelta(minutes=1),
        )

        total_events = await workflow.execute_activity(
            get_events_count,
            GetEventsCountInputs(
                team_id=inputs.team_id,
                interval_start=interval_start_str,
                interval_end=interval_end_str,
                exclude_events=batch_export_details.exclude_events,
                include_events=batch_export_details.include_events,
            ),
            start_to_close_timeout=dt.timedelta(hours=1),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=dt.timedelta(seconds=20)),
            heartbeat_timeout=dt.timedelta(minutes=1),
        )

        return await workflow.execute_activity(
            compare_counts,
            CompareCountsInputs(total_completed_records=total_completed_records, total_events=total_events),
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=dt.timedelta(seconds=20)),
            heartbeat_timeout=dt.timedelta(minutes=1),
        )
