import asyncio
import dataclasses
import datetime as dt
import json
import typing

import temporalio.activity
import temporalio.common
import temporalio.workflow

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tag_queries, Product
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_internal_logger
from posthog.temporal.session_recordings.queries import get_sampled_session_ids


@dataclasses.dataclass(frozen=True)
class CompareRecordingConsoleLogsActivityInputs:
    """Inputs for the console logs comparison activity."""

    started_after: str = dataclasses.field()
    started_before: str = dataclasses.field()
    sample_size: int = dataclasses.field(default=100)

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "started_after": self.started_after,
            "started_before": self.started_before,
            "sample_size": self.sample_size,
        }


def get_console_logs(
    table_name: str,
    session_ids: list[tuple[str, int]],  # [(session_id, team_id), ...]
) -> dict[tuple[str, int], list[dict]]:
    """Get console logs from the specified table for given session IDs."""
    if not session_ids:
        return {}

    # Format session IDs and team IDs for the IN clause
    session_id_tuples = ", ".join([f"('{sid}', {tid})" for sid, tid in session_ids])

    query = """
        SELECT
            log_source_id,
            team_id,
            timestamp,
            level,
            message,
            instance_id
        FROM {table}
        WHERE (log_source_id, team_id) IN ({session_id_tuples})
        ORDER BY timestamp
    """

    results = sync_execute(query.format(table=table_name, session_id_tuples=session_id_tuples))

    # Group results by session_id and team_id
    logs_by_session: dict[tuple[str, int], list[dict]] = {}
    for row in results:
        session_key = (str(row[0]), int(row[1]))  # (log_source_id, team_id)
        log_entry = {"timestamp": row[2], "level": row[3], "message": row[4], "instance_id": row[5]}

        if session_key not in logs_by_session:
            logs_by_session[session_key] = []
        logs_by_session[session_key].append(log_entry)

    return logs_by_session


def deduplicate_logs(entries: list[dict]) -> list[dict]:
    """Deduplicate logs using the same logic as session-console-log-recorder.ts."""
    seen = set()
    deduped = []

    for entry in entries:
        fingerprint = f"{entry['level']}-{entry['message']}"
        if fingerprint not in seen:
            deduped.append(entry)
            seen.add(fingerprint)

    return deduped


def get_console_logs_v1(session_ids: list[tuple[str, int]]) -> dict[tuple[str, int], list[dict]]:
    """Get console logs from v1 storage for given session IDs."""
    return get_console_logs("log_entries", session_ids)


def get_console_logs_v2(session_ids: list[tuple[str, int]]) -> dict[tuple[str, int], list[dict]]:
    """Get console logs from v2 storage for given session IDs."""
    return get_console_logs("log_entries_v2_test", session_ids)


@temporalio.activity.defn
async def compare_recording_console_logs_activity(inputs: CompareRecordingConsoleLogsActivityInputs) -> None:
    """Compare console logs between v1 and v2 storage for a sample of sessions."""
    logger = get_internal_logger()
    start_time = dt.datetime.now()
    tag_queries(product=Product.REPLAY)

    await logger.ainfo(
        "Starting console logs comparison activity",
        started_after=inputs.started_after,
        started_before=inputs.started_before,
        sample_size=inputs.sample_size,
    )

    async with Heartbeater():
        started_after = dt.datetime.fromisoformat(inputs.started_after)
        started_before = dt.datetime.fromisoformat(inputs.started_before)

        # Get sample of session IDs
        session_ids = await asyncio.to_thread(
            get_sampled_session_ids,
            started_after,
            started_before,
            inputs.sample_size,
        )

        # Fetch raw logs from both systems
        v1_logs_raw, v2_logs_raw = await asyncio.gather(
            asyncio.to_thread(get_console_logs_v1, session_ids),
            asyncio.to_thread(get_console_logs_v2, session_ids),
        )

        # Track duplication stats
        v1_total_raw = 0
        v1_total_deduped = 0
        v2_total_raw = 0
        v2_total_deduped = 0

        # Deduplicate logs and track stats
        v1_logs = {}
        v2_logs = {}

        for session_key, raw_entries in v1_logs_raw.items():
            v1_total_raw += len(raw_entries)
            deduped = deduplicate_logs(raw_entries)
            v1_total_deduped += len(deduped)
            v1_logs[session_key] = deduped

        for session_key, raw_entries in v2_logs_raw.items():
            v2_total_raw += len(raw_entries)
            deduped = deduplicate_logs(raw_entries)
            v2_total_deduped += len(deduped)
            v2_logs[session_key] = deduped

        # Compare results
        differing_sessions = []
        missing_in_v2 = []
        missing_in_v1 = []
        differences_by_type = {
            "count_mismatch": 0,
            "content_mismatch": 0,
        }

        for session_key in set(v1_logs.keys()) | set(v2_logs.keys()):
            session_id, team_id = session_key

            if session_key not in v2_logs:
                missing_in_v2.append(session_key)
                continue
            if session_key not in v1_logs:
                missing_in_v1.append(session_key)
                continue

            v1_entries = v1_logs[session_key]
            v2_entries = v2_logs[session_key]

            if len(v1_entries) != len(v2_entries):
                differences_by_type["count_mismatch"] += 1
                differing_sessions.append(session_key)

                # Create sets of entries for comparison
                v1_set = {(e["level"], e["message"]) for e in v1_entries}
                v2_set = {(e["level"], e["message"]) for e in v2_entries}

                common_entries = v1_set & v2_set
                only_in_v1 = v1_set - v2_set
                only_in_v2 = v2_set - v1_set

                await logger.ainfo(
                    "Log entry count mismatch",
                    session_id=session_id,
                    team_id=team_id,
                    v1_total=len(v1_entries),
                    v2_total=len(v2_entries),
                    common_count=len(common_entries),
                    only_in_v1_count=len(only_in_v1),
                    only_in_v2_count=len(only_in_v2),
                    # Include example entries that differ
                    example_only_in_v1=list(only_in_v1)[:3] if only_in_v1 else None,
                    example_only_in_v2=list(only_in_v2)[:3] if only_in_v2 else None,
                )
                continue

            # Compare entries in order for content mismatches
            for i, (v1_entry, v2_entry) in enumerate(zip(v1_entries, v2_entries)):
                if (
                    v1_entry["level"] != v2_entry["level"]
                    or v1_entry["message"] != v2_entry["message"]
                    or v1_entry["timestamp"] != v2_entry["timestamp"]
                ):
                    differences_by_type["content_mismatch"] += 1
                    differing_sessions.append(session_key)
                    await logger.ainfo(
                        "Log entry content mismatch",
                        session_id=session_id,
                        team_id=team_id,
                        entry_index=i,
                        v1_entry=v1_entry,
                        v2_entry=v2_entry,
                        differences={
                            "level": v1_entry["level"] != v2_entry["level"],
                            "message": v1_entry["message"] != v2_entry["message"],
                            "timestamp": v1_entry["timestamp"] != v2_entry["timestamp"],
                        },
                    )
                    break

        # Calculate duplication percentages
        v1_duplication_rate = ((v1_total_raw - v1_total_deduped) / v1_total_raw * 100) if v1_total_raw > 0 else 0
        v2_duplication_rate = ((v2_total_raw - v2_total_deduped) / v2_total_raw * 100) if v2_total_raw > 0 else 0

        # Log summary with more detailed statistics
        await logger.ainfo(
            "Completed console logs comparison activity",
            duration_seconds=(dt.datetime.now() - start_time).total_seconds(),
            sampled_sessions=len(session_ids),
            differing_sessions=len(differing_sessions),
            missing_in_v1=len(missing_in_v1),
            missing_in_v2=len(missing_in_v2),
            differences_by_type=differences_by_type,
            duplication_stats={
                "v1": {
                    "raw_events": v1_total_raw,
                    "deduped_events": v1_total_deduped,
                    "duplication_rate": round(v1_duplication_rate, 2),
                },
                "v2": {
                    "raw_events": v2_total_raw,
                    "deduped_events": v2_total_deduped,
                    "duplication_rate": round(v2_duplication_rate, 2),
                },
            },
            time_range={
                "started_after": started_after.isoformat(),
                "started_before": started_before.isoformat(),
            },
        )


@dataclasses.dataclass(frozen=True)
class CompareRecordingConsoleLogsWorkflowInputs:
    """Inputs for the console logs comparison workflow."""

    started_after: str = dataclasses.field()
    started_before: str = dataclasses.field()
    window_seconds: int = dataclasses.field(default=300)  # 5 minutes default
    sample_size: int = dataclasses.field(default=100)

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "started_after": self.started_after,
            "started_before": self.started_before,
            "window_seconds": self.window_seconds,
            "sample_size": self.sample_size,
        }


@temporalio.workflow.defn(name="compare-recording-console-logs")
class CompareRecordingConsoleLogsWorkflow(PostHogWorkflow):
    """Workflow to compare session recording console logs between storage backends."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.paused = False

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CompareRecordingConsoleLogsWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])

        for field in ["started_after", "started_before"]:
            if field not in loaded:
                raise ValueError(f"Required field {field} not provided")
            loaded[field] = dt.datetime.fromisoformat(loaded[field])

        window_seconds = loaded.get("window_seconds", 300)
        if not isinstance(window_seconds, int) or window_seconds <= 0:
            raise ValueError("window_seconds must be a positive integer")

        sample_size = loaded.get("sample_size", 100)
        if not isinstance(sample_size, int) or sample_size <= 0:
            raise ValueError("sample_size must be a positive integer")

        return CompareRecordingConsoleLogsWorkflowInputs(
            started_after=loaded["started_after"],
            started_before=loaded["started_before"],
            window_seconds=window_seconds,
            sample_size=sample_size,
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
    async def run(self, inputs: CompareRecordingConsoleLogsWorkflowInputs):
        """Run the comparison of session recording console logs."""
        await temporalio.workflow.wait_condition(lambda: not self.paused)

        started_after = dt.datetime.fromisoformat(inputs.started_after)
        started_before = dt.datetime.fromisoformat(inputs.started_before)

        logger = get_internal_logger()
        workflow_start = dt.datetime.now()

        logger.info(
            "Starting console logs comparison workflow",
            started_after=started_after,
            started_before=started_before,
            window_seconds=inputs.window_seconds,
            sample_size=inputs.sample_size,
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

            activity_inputs = CompareRecordingConsoleLogsActivityInputs(
                started_after=window_start.isoformat(),
                started_before=window_end.isoformat(),
                sample_size=inputs.sample_size,
            )

            await temporalio.workflow.execute_activity(
                compare_recording_console_logs_activity,
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
            "Completed console logs comparison workflow",
            duration_seconds=duration,
            windows_processed=len(windows),
        )

    @temporalio.workflow.update
    async def pause(self) -> None:
        """Signal handler for workflow to pause or unpause."""
        async with self.lock:
            if self.paused is True:
                self.paused = False
            else:
                self.paused = True
