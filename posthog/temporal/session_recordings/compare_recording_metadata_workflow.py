import asyncio
import dataclasses
import datetime as dt
import json
import typing
import statistics

import temporalio.activity
import temporalio.common
import temporalio.workflow

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tag_queries, Product
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_internal_logger


def get_session_replay_events(
    table_name: str,
    started_after: dt.datetime,
    started_before: dt.datetime,
    session_length_limit_seconds: int = 172800,
    timestamp_leeway_seconds: int = 0,
) -> list[tuple]:
    """Get session replay events from the specified table within the time range."""
    query = """
        SELECT
            session_id,
            team_id,
            any(distinct_id) as distinct_id,
            min(min_first_timestamp) as min_first_timestamp_agg,
            max(max_last_timestamp) as max_last_timestamp_agg,
            argMinMerge(first_url) as first_url,
            groupUniqArrayArray(all_urls) as all_urls,
            sum(click_count) as click_count,
            sum(keypress_count) as keypress_count,
            sum(mouse_activity_count) as mouse_activity_count,
            sum(active_milliseconds) as active_milliseconds,
            sum(console_log_count) as console_log_count,
            sum(console_warn_count) as console_warn_count,
            sum(console_error_count) as console_error_count,
            sum(event_count) as event_count,
            argMinMerge(snapshot_source) as snapshot_source,
            argMinMerge(snapshot_library) as snapshot_library
            {block_fields}
        FROM (
            SELECT *
            FROM {table}
            WHERE min_first_timestamp >= toDateTime(%(started_after)s) - INTERVAL %(timestamp_leeway)s SECOND
            AND max_last_timestamp <= toDateTime(%(started_before)s) + INTERVAL {session_length_limit_seconds} SECOND + INTERVAL %(timestamp_leeway)s SECOND
            ORDER BY min_first_timestamp ASC
        )
        GROUP BY
            session_id,
            team_id
        HAVING
            min_first_timestamp_agg >= toDateTime(%(started_after)s)
            AND min_first_timestamp_agg <= toDateTime(%(started_before)s)
            AND max_last_timestamp_agg <= min_first_timestamp_agg + INTERVAL {session_length_limit_seconds} SECOND
    """

    # Add block-related fields only for v2 table
    block_fields = (
        """
        ,groupArrayArray(block_first_timestamps) as block_first_timestamps,
        groupArrayArray(block_last_timestamps) as block_last_timestamps,
        groupArrayArray(block_urls) as block_urls
    """
        if "_v2_" in table_name
        else ""
    )

    return sync_execute(
        query.format(
            table=table_name, block_fields=block_fields, session_length_limit_seconds=session_length_limit_seconds
        ),
        {
            "started_after": started_after.strftime("%Y-%m-%d %H:%M:%S"),
            "started_before": started_before.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp_leeway": timestamp_leeway_seconds,
        },
    )


FIELD_NAMES = [
    "distinct_id",
    "min_first_timestamp_agg",
    "max_last_timestamp_agg",
    "first_url",
    "all_urls",
    "click_count",
    "keypress_count",
    "mouse_activity_count",
    "active_milliseconds",
    "console_log_count",
    "console_warn_count",
    "console_error_count",
    "event_count",
    "snapshot_source",
    "snapshot_library",
]


@dataclasses.dataclass(frozen=True)
class CompareRecordingMetadataActivityInputs:
    """Inputs for the `compare_recording_metadata_activity`."""

    started_after: str = dataclasses.field()
    started_before: str = dataclasses.field()
    window_result_limit: int | None = dataclasses.field(default=None)
    session_length_limit_seconds: int = dataclasses.field(default=172800)  # 48h default
    timestamp_leeway_seconds: int = dataclasses.field(default=0)  # No leeway by default

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "started_after": self.started_after,
            "started_before": self.started_before,
            "window_result_limit": self.window_result_limit,
            "session_length_limit_seconds": self.session_length_limit_seconds,
            "timestamp_leeway_seconds": self.timestamp_leeway_seconds,
        }


@temporalio.activity.defn
async def compare_recording_metadata_activity(inputs: CompareRecordingMetadataActivityInputs) -> None:
    """Compare session recording metadata between storage backends."""
    logger = get_internal_logger()
    start_time = dt.datetime.now()
    tag_queries(product=Product.REPLAY)
    await logger.ainfo(
        "Starting comparison activity for time range %s to %s%s%s",
        inputs.started_after,
        inputs.started_before,
        f" (limiting to {inputs.window_result_limit} sessions)" if inputs.window_result_limit else "",
        f" (session length limit: {inputs.session_length_limit_seconds}s)"
        if inputs.session_length_limit_seconds
        else "",
    )

    async with Heartbeater():
        started_after = dt.datetime.fromisoformat(inputs.started_after)
        started_before = dt.datetime.fromisoformat(inputs.started_before)

        results_v1, results_v2 = await asyncio.gather(
            asyncio.to_thread(
                get_session_replay_events,
                "session_replay_events",
                started_after,
                started_before,
                inputs.session_length_limit_seconds,
                inputs.timestamp_leeway_seconds,
            ),
            asyncio.to_thread(
                get_session_replay_events,
                "session_replay_events_v2_test",
                started_after,
                started_before,
                inputs.session_length_limit_seconds,
                inputs.timestamp_leeway_seconds,
            ),
        )

        # Create lookup tables for easier comparison
        v1_sessions = {(r[0], r[1]): r for r in results_v1}  # (session_id, team_id) -> full record
        v2_sessions = {(r[0], r[1]): r for r in results_v2}

        # Find sessions in v1 but not in v2
        only_in_v1 = list(set(v1_sessions.keys()) - set(v2_sessions.keys()))

        # Find sessions in v2 but not in v1
        only_in_v2 = list(set(v2_sessions.keys()) - set(v1_sessions.keys()))

        # Compare data for sessions in both
        all_differing_sessions: list[tuple[str, int]] = []  # (session_id, team_id)
        all_differing_sessions_excluding_active_ms: list[tuple[str, int]] = []  # (session_id, team_id)
        differing_sessions_count = 0
        active_ms_diffs_percentage: list[float] = []
        field_differences: dict[str, int] = {field: 0 for field in FIELD_NAMES}  # Track per-field differences
        field_example_sessions: dict[str, list[tuple[str, int, typing.Any, typing.Any]]] = {
            field: [] for field in FIELD_NAMES
        }  # Track example sessions per field

        for session_key in set(v1_sessions.keys()) & set(v2_sessions.keys()):
            session_id, team_id = session_key
            v1_data = v1_sessions[session_key]
            v2_data = v2_sessions[session_key]

            # Calculate active_ms percentage difference
            v1_active_ms = v1_data[
                FIELD_NAMES.index("active_milliseconds") + 2
            ]  # +2 because session_id and team_id are at index 0,1
            v2_active_ms = v2_data[FIELD_NAMES.index("active_milliseconds") + 2]
            if v1_active_ms > 0:  # Avoid division by zero
                diff_percentage = ((v2_active_ms - v1_active_ms) / v1_active_ms) * 100
                active_ms_diffs_percentage.append(diff_percentage)

            # Compare each field and collect differences
            differences = []
            differences_excluding_active_ms = []
            for i, field_name in enumerate(
                FIELD_NAMES, start=2
            ):  # start=2 because session_id and team_id are at index 0,1
                if v1_data[i] != v2_data[i]:
                    diff = {"field": field_name, "v1_value": v1_data[i], "v2_value": v2_data[i]}
                    differences.append(diff)
                    field_differences[field_name] += 1
                    # Store example session if we haven't stored 3 examples for this field yet
                    if len(field_example_sessions[field_name]) < 3:
                        field_example_sessions[field_name].append((session_id, team_id, v1_data[i], v2_data[i]))
                    if field_name != "active_milliseconds":
                        differences_excluding_active_ms.append(diff)

            if differences:
                all_differing_sessions.append(session_key)
                differing_sessions_count += 1
                # Only log detailed differences if within limit and there are differences beyond active_milliseconds
                if (
                    not inputs.window_result_limit or differing_sessions_count <= inputs.window_result_limit
                ) and differences_excluding_active_ms:
                    await logger.ainfo(
                        "Found differences in session", session_id=session_id, team_id=team_id, differences=differences
                    )

            if differences_excluding_active_ms:
                all_differing_sessions_excluding_active_ms.append(session_key)

        end_time = dt.datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Calculate active_ms statistics
        active_ms_stats = {}
        if active_ms_diffs_percentage:
            active_ms_stats = {
                "avg_percentage_diff": round(statistics.mean(active_ms_diffs_percentage), 2),
                "std_dev_percentage_diff": round(
                    statistics.stdev(active_ms_diffs_percentage) if len(active_ms_diffs_percentage) > 1 else 0, 2
                ),
                "samples": len(active_ms_diffs_percentage),
            }

        # Log summary
        await logger.ainfo(
            "Completed comparison activity",
            duration_seconds=duration,
            v1_count=len(results_v1),
            v2_count=len(results_v2),
            only_in_v1_count=len(only_in_v1),
            only_in_v2_count=len(only_in_v2),
            total_differing_sessions=len(all_differing_sessions),
            total_differing_sessions_excluding_active_ms=len(all_differing_sessions_excluding_active_ms),
            active_ms_stats=active_ms_stats,
            field_differences=field_differences,
            time_range={
                "started_after": started_after.isoformat(),
                "started_before": started_before.isoformat(),
            },
        )

        # Log example differences for each field separately
        for field_name, examples in field_example_sessions.items():
            if examples:  # Only log fields that have differences
                await logger.ainfo(
                    f"Example differences for field: {field_name}",
                    field=field_name,
                    examples=[
                        {"session_id": session_id, "team_id": team_id, "v1_value": v1_value, "v2_value": v2_value}
                        for session_id, team_id, v1_value, v2_value in examples
                    ],
                )

        # Log sessions only in v1/v2 if any exist
        if only_in_v1:
            await logger.ainfo(
                "Sessions only in v1",
                session_ids=only_in_v1,  # Already (session_id, team_id) tuples
            )
        if only_in_v2:
            await logger.ainfo(
                "Sessions only in v2",
                session_ids=only_in_v2,  # Already (session_id, team_id) tuples
            )


@dataclasses.dataclass(frozen=True)
class CompareRecordingMetadataWorkflowInputs:
    """Inputs for the `CompareRecordingMetadataWorkflow`."""

    started_after: str = dataclasses.field()
    started_before: str = dataclasses.field()
    window_seconds: int = dataclasses.field(default=300)  # 5 minutes default
    window_result_limit: int | None = dataclasses.field(default=None)  # No limit by default
    session_length_limit_seconds: int = dataclasses.field(default=172800)  # 48h default
    timestamp_leeway_seconds: int = dataclasses.field(default=0)  # No leeway by default

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "started_after": self.started_after,
            "started_before": self.started_before,
            "window_seconds": self.window_seconds,
            "window_result_limit": self.window_result_limit,
            "session_length_limit_seconds": self.session_length_limit_seconds,
            "timestamp_leeway_seconds": self.timestamp_leeway_seconds,
        }


@temporalio.workflow.defn(name="compare-recording-metadata")
class CompareRecordingMetadataWorkflow(PostHogWorkflow):
    """Workflow to compare session recording metadata between storage backends."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.paused = False

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CompareRecordingMetadataWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        # Convert ISO format strings to datetime objects
        for field in ["started_after", "started_before"]:
            if field not in loaded:
                raise ValueError(f"Required field {field} not provided")
            loaded[field] = dt.datetime.fromisoformat(loaded[field])

        window_seconds = loaded.get("window_seconds", 300)
        if not isinstance(window_seconds, int) or window_seconds <= 0:
            raise ValueError("window_seconds must be a positive integer")

        window_result_limit = loaded.get("window_result_limit")
        if window_result_limit is not None and not isinstance(window_result_limit, int | None):
            raise ValueError("window_result_limit must be an integer or None")

        session_length_limit_seconds = loaded.get("session_length_limit_seconds", 172800)
        if not isinstance(session_length_limit_seconds, int) or session_length_limit_seconds <= 0:
            raise ValueError("session_length_limit_seconds must be a positive integer")

        timestamp_leeway_seconds = loaded.get("timestamp_leeway_seconds", 0)
        if not isinstance(timestamp_leeway_seconds, int) or timestamp_leeway_seconds < 0:
            raise ValueError("timestamp_leeway_seconds must be a non-negative integer")

        return CompareRecordingMetadataWorkflowInputs(
            started_after=loaded["started_after"],
            started_before=loaded["started_before"],
            window_seconds=window_seconds,
            window_result_limit=window_result_limit,
            session_length_limit_seconds=session_length_limit_seconds,
            timestamp_leeway_seconds=timestamp_leeway_seconds,
        )

    @staticmethod
    def generate_time_windows(
        start_time: dt.datetime, end_time: dt.datetime, window_seconds: int
    ) -> list[tuple[dt.datetime, dt.datetime]]:
        """Generate time windows between start and end time."""
        windows = []
        current = start_time

        while current < end_time:
            window_end = min(current + dt.timedelta(seconds=window_seconds), end_time)
            windows.append((current, window_end))
            current = window_end

        return windows

    @temporalio.workflow.run
    async def run(self, inputs: CompareRecordingMetadataWorkflowInputs):
        """Run the comparison of session recording metadata."""
        await temporalio.workflow.wait_condition(lambda: not self.paused)

        started_after = dt.datetime.fromisoformat(inputs.started_after)
        started_before = dt.datetime.fromisoformat(inputs.started_before)

        logger = get_internal_logger()
        workflow_start = dt.datetime.now()
        logger.info(
            "Starting comparison workflow for sessions between %s and %s using %d second windows%s%s",
            started_after,
            started_before,
            inputs.window_seconds,
            f" (limiting to {inputs.window_result_limit} sessions per window)" if inputs.window_result_limit else "",
            f" (with {inputs.timestamp_leeway_seconds}s timestamp leeway)" if inputs.timestamp_leeway_seconds else "",
        )

        # Generate time windows
        windows = self.generate_time_windows(started_after, started_before, inputs.window_seconds)
        logger.info("Generated %d time windows to process", len(windows))

        # Process each window
        for i, (window_start, window_end) in enumerate(windows, 1):
            logger.info(
                "Processing window %d/%d: %s to %s",
                i,
                len(windows),
                window_start,
                window_end,
            )
            activity_inputs = CompareRecordingMetadataActivityInputs(
                started_after=window_start.isoformat(),
                started_before=window_end.isoformat(),
                window_result_limit=inputs.window_result_limit,
                session_length_limit_seconds=inputs.session_length_limit_seconds,
                timestamp_leeway_seconds=inputs.timestamp_leeway_seconds,
            )

            await temporalio.workflow.execute_activity(
                compare_recording_metadata_activity,
                activity_inputs,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=1,
                    non_retryable_error_types=[],
                ),
            )

        workflow_end = dt.datetime.now()
        duration = (workflow_end - workflow_start).total_seconds()
        logger.info(
            "Completed comparison workflow in %.2f seconds. Processed %d time windows",
            duration,
            len(windows),
        )

    @temporalio.workflow.update
    async def pause(self) -> None:
        """Signal handler for workflow to pause or unpause."""
        async with self.lock:
            if self.paused is True:
                self.paused = False
            else:
                self.paused = True
