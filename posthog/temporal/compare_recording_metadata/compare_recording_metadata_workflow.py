import asyncio
import dataclasses
import datetime as dt
import json
import typing

import temporalio.activity
import temporalio.common
import temporalio.workflow

from posthog.clickhouse.client import sync_execute
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_internal_logger


def get_session_replay_events(
    table_name: str,
    started_after: dt.datetime,
    started_before: dt.datetime,
) -> list[tuple]:
    """Get session replay events from the specified table within the time range."""
    query = """
        SELECT
            session_id,
            any(distinct_id) as distinct_id,
            min(min_first_timestamp) as min_first_timestamp,
            max(max_last_timestamp) as max_last_timestamp,
            argMinMerge(first_url) as first_url,
            groupUniqArrayArray(all_urls) as all_urls,
            sum(click_count) as click_count,
            sum(keypress_count) as keypress_count,
            sum(mouse_activity_count) as mouse_activity_count,
            sum(active_milliseconds) as active_milliseconds,
            sum(console_log_count) as console_log_count,
            sum(console_warn_count) as console_warn_count,
            sum(console_error_count) as console_error_count,
            sum(size) as size,
            sum(message_count) as message_count,
            sum(event_count) as event_count,
            argMinMerge(snapshot_source) as snapshot_source,
            argMinMerge(snapshot_library) as snapshot_library
            {block_fields}
        FROM
            {table}
        GROUP BY
            session_id
        HAVING
            min_first_timestamp >= toDateTime(%(started_after)s)
            AND min_first_timestamp <= toDateTime(%(started_before)s)
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
        query.format(table=table_name, block_fields=block_fields),
        {
            "started_after": started_after.strftime("%Y-%m-%d %H:%M:%S"),
            "started_before": started_before.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )


FIELD_NAMES = [
    "distinct_id",
    "min_first_timestamp",
    "max_last_timestamp",
    "first_url",
    "all_urls",
    "click_count",
    "keypress_count",
    "mouse_activity_count",
    "active_milliseconds",
    "console_log_count",
    "console_warn_count",
    "console_error_count",
    "size",
    "message_count",
    "event_count",
    "snapshot_source",
    "snapshot_library",
]


@dataclasses.dataclass(frozen=True)
class CompareRecordingMetadataActivityInputs:
    """Inputs for the `compare_recording_metadata_activity`."""

    started_after: str = dataclasses.field()
    started_before: str = dataclasses.field()

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "started_after": self.started_after,
            "started_before": self.started_before,
        }


@temporalio.activity.defn
async def compare_recording_metadata_activity(inputs: CompareRecordingMetadataActivityInputs) -> None:
    """Compare session recording metadata between storage backends."""
    async with Heartbeater():
        logger = get_internal_logger()
        started_after = dt.datetime.fromisoformat(inputs.started_after)
        started_before = dt.datetime.fromisoformat(inputs.started_before)

        results_v1, results_v2 = await asyncio.gather(
            asyncio.to_thread(
                get_session_replay_events,
                "session_replay_events",
                started_after,
                started_before,
            ),
            asyncio.to_thread(
                get_session_replay_events,
                "session_replay_events_v2_test",
                started_after,
                started_before,
            ),
        )

        await logger.ainfo(
            "Found %d session recordings in v1 and %d in v2 that started between %s and %s",
            len(results_v1),
            len(results_v2),
            started_after,
            started_before,
        )

        # Create lookup tables for easier comparison
        v1_sessions = {r[0]: r for r in results_v1}  # session_id -> full record
        v2_sessions = {r[0]: r for r in results_v2}

        # Find sessions in v1 but not in v2
        only_in_v1 = set(v1_sessions.keys()) - set(v2_sessions.keys())
        if only_in_v1:
            await logger.ainfo("Sessions only in v1: %s", only_in_v1)

        # Find sessions in v2 but not in v1
        only_in_v2 = set(v2_sessions.keys()) - set(v1_sessions.keys())
        if only_in_v2:
            await logger.ainfo("Sessions only in v2: %s", only_in_v2)

        # Compare data for sessions in both
        for session_id in set(v1_sessions.keys()) & set(v2_sessions.keys()):
            v1_data = v1_sessions[session_id]
            v2_data = v2_sessions[session_id]

            # Compare each field and collect differences
            differences = []
            for i, field_name in enumerate(FIELD_NAMES, start=1):  # start=1 because session_id is at index 0
                if v1_data[i] != v2_data[i]:
                    differences.append(f"{field_name}: v1={v1_data[i]} v2={v2_data[i]}")

            if differences:
                await logger.ainfo("Session %s differences:\n%s", session_id, "\n".join(differences))


@dataclasses.dataclass(frozen=True)
class CompareRecordingMetadataWorkflowInputs:
    """Inputs for the `CompareRecordingMetadataWorkflow`."""

    started_after: str = dataclasses.field()
    started_before: str = dataclasses.field()
    window_seconds: int = dataclasses.field(default=300)  # 5 minutes default

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "started_after": self.started_after,
            "started_before": self.started_before,
            "window_seconds": self.window_seconds,
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

        # Optional window_seconds with default
        window_seconds = loaded.get("window_seconds", 300)
        if not isinstance(window_seconds, int) or window_seconds <= 0:
            raise ValueError("window_seconds must be a positive integer")

        return CompareRecordingMetadataWorkflowInputs(
            started_after=loaded["started_after"],
            started_before=loaded["started_before"],
            window_seconds=window_seconds,
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
        logger.info(
            "Starting comparison for sessions between %s and %s using %d second windows",
            started_after,
            started_before,
            inputs.window_seconds,
        )

        # Generate time windows
        windows = self.generate_time_windows(started_after, started_before, inputs.window_seconds)

        # Process each window
        for window_start, window_end in windows:
            activity_inputs = CompareRecordingMetadataActivityInputs(
                started_after=window_start.isoformat(),
                started_before=window_end.isoformat(),
            )

            await temporalio.workflow.execute_activity(
                compare_recording_metadata_activity,
                activity_inputs,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=0,
                    non_retryable_error_types=[],
                ),
            )

    @temporalio.workflow.update
    async def pause(self) -> None:
        """Signal handler for workflow to pause or unpause."""
        async with self.lock:
            if self.paused is True:
                self.paused = False
            else:
                self.paused = True
