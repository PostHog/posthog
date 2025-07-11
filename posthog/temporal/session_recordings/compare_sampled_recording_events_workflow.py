import asyncio
import dataclasses
import datetime as dt
import json
import typing

import temporalio.activity
import temporalio.common
import temporalio.workflow
from asgiref.sync import sync_to_async

from posthog.clickhouse.query_tagging import tag_queries, Product
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_internal_logger
from posthog.temporal.session_recordings.queries import get_sampled_session_ids
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.models import Team
from posthog.temporal.session_recordings.session_comparer import (
    get_url_from_event,
    add_url,
    count_events_per_window,
    group_events_by_type,
    is_click,
    is_mouse_activity,
    is_keypress,
    is_console_log,
    get_console_level,
)
from posthog.temporal.session_recordings.queries import get_session_metadata
from posthog.temporal.session_recordings.snapshot_utils import fetch_v1_snapshots, fetch_v2_snapshots
from posthog.temporal.session_recordings.segmentation import compute_active_milliseconds


@dataclasses.dataclass(frozen=True)
class CompareSampledRecordingEventsActivityInputs:
    """Inputs for the recording events comparison activity."""

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


@temporalio.activity.defn
async def compare_sampled_recording_events_activity(inputs: CompareSampledRecordingEventsActivityInputs) -> None:
    """Compare recording events between v1 and v2 storage for a sample of sessions."""
    logger = get_internal_logger()
    start_time = dt.datetime.now()
    tag_queries(product=Product.REPLAY)

    await logger.ainfo(
        "Starting sampled events comparison activity",
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

        for session_id, team_id in session_ids:
            await logger.ainfo(
                "Processing session",
                session_id=session_id,
                team_id=team_id,
            )

            team = await sync_to_async(Team.objects.get)(id=team_id)
            recording = await sync_to_async(SessionRecording.get_or_build)(session_id=session_id, team=team)

            # Get v1 and v2 snapshots using the shared utility functions
            try:
                v1_snapshots = await asyncio.to_thread(fetch_v1_snapshots, recording)
            except Exception as e:
                await logger.awarn(
                    "Skipping session due to error when fetching v1 snapshots",
                    session_id=session_id,
                    team_id=team_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                continue

            try:
                v2_snapshots = await asyncio.to_thread(fetch_v2_snapshots, recording)
            except Exception as e:
                await logger.awarn(
                    "Skipping session due to error when fetching v2 snapshots",
                    session_id=session_id,
                    team_id=team_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                continue

            # Convert snapshots to dictionaries for counting duplicates
            v1_events: dict[str, int] = {}
            v2_events: dict[str, int] = {}

            for s in v1_snapshots:
                event_key = json.dumps((s["window_id"], s["data"]), sort_keys=True)
                v1_events[event_key] = v1_events.get(event_key, 0) + 1

            for s in v2_snapshots:
                event_key = json.dumps((s["window_id"], s["data"]), sort_keys=True)
                v2_events[event_key] = v2_events.get(event_key, 0) + 1

            # Find events in both versions with their counts
            all_keys = set(v1_events.keys()) | set(v2_events.keys())
            common_events = {
                k: (v1_events.get(k, 0), v2_events.get(k, 0)) for k in all_keys if k in v1_events and k in v2_events
            }
            only_in_v1 = {k: v1_events[k] for k in v1_events.keys() - v2_events.keys()}
            only_in_v2 = {k: v2_events[k] for k in v2_events.keys() - v1_events.keys()}

            # Get metadata counts
            v1_metadata = get_session_metadata(team.pk, recording.session_id, "session_replay_events")
            v2_metadata = get_session_metadata(team.pk, recording.session_id, "session_replay_events_v2_test")

            # Track URLs for both versions
            v1_urls: set[str] = set()
            v1_first_url: str | None = None
            v2_urls: set[str] = set()
            v2_first_url: str | None = None

            # Count events by type in v1
            v1_click_count = 0
            v1_mouse_activity_count = 0
            v1_keypress_count = 0
            v1_console_log_count = 0
            v1_console_warn_count = 0
            v1_console_error_count = 0

            for snapshot in v1_snapshots:
                data = snapshot["data"]
                if is_click(data):
                    v1_click_count += 1
                if is_mouse_activity(data):
                    v1_mouse_activity_count += 1
                if is_keypress(data):
                    v1_keypress_count += 1
                if is_console_log(data):
                    level = get_console_level(data)
                    if level in [
                        "log",
                        "info",
                        "count",
                        "timeEnd",
                        "trace",
                        "dir",
                        "dirxml",
                        "group",
                        "groupCollapsed",
                        "debug",
                        "timeLog",
                    ]:
                        v1_console_log_count += 1
                    elif level in ["warn", "countReset"]:
                        v1_console_warn_count += 1
                    elif level in ["error", "assert"]:
                        v1_console_error_count += 1
                    else:  # default to log level for unknown levels
                        v1_console_log_count += 1

                # Extract URL
                url = get_url_from_event(data)
                if url:
                    if v1_first_url is None:
                        v1_first_url = url[:4096] if len(url) > 4096 else url
                    add_url(v1_urls, url)

            # Count events by type in v2
            v2_click_count = 0
            v2_mouse_activity_count = 0
            v2_keypress_count = 0
            v2_console_log_count = 0
            v2_console_warn_count = 0
            v2_console_error_count = 0

            for snapshot in v2_snapshots:
                data = snapshot["data"]
                if is_click(data):
                    v2_click_count += 1
                if is_mouse_activity(data):
                    v2_mouse_activity_count += 1
                if is_keypress(data):
                    v2_keypress_count += 1
                if is_console_log(data):
                    level = get_console_level(data)
                    if level in [
                        "log",
                        "info",
                        "count",
                        "timeEnd",
                        "trace",
                        "dir",
                        "dirxml",
                        "group",
                        "groupCollapsed",
                        "debug",
                        "timeLog",
                    ]:
                        v2_console_log_count += 1
                    elif level in ["warn", "countReset"]:
                        v2_console_warn_count += 1
                    elif level in ["error", "assert"]:
                        v2_console_error_count += 1
                    else:  # default to log level for unknown levels
                        v2_console_log_count += 1

                # Extract URL
                url = get_url_from_event(data)
                if url:
                    if v2_first_url is None:
                        v2_first_url = url[:4096] if len(url) > 4096 else url
                    add_url(v2_urls, url)

            # Compare URLs
            await logger.ainfo(
                "URL comparison",
                session_id=session_id,
                team_id=team_id,
                v1_first_url=v1_first_url,
                v2_first_url=v2_first_url,
                first_url_matches=v1_first_url == v2_first_url,
                v1_url_count=len(v1_urls),
                v2_url_count=len(v2_urls),
                urls_in_both=len(v1_urls & v2_urls),
                only_in_v1=sorted(v1_urls - v2_urls)[:5],  # Show up to 5 examples
                only_in_v2=sorted(v2_urls - v1_urls)[:5],  # Show up to 5 examples
                metadata_comparison={
                    "v1": {
                        "first_url": v1_metadata["first_url"],
                        "all_urls": v1_metadata["all_urls"],
                        "first_url_matches_snapshot": v1_metadata["first_url"] == v1_first_url,
                        "all_urls_match_snapshot": set(v1_metadata["all_urls"]) == v1_urls,
                    },
                    "v2": {
                        "first_url": v2_metadata["first_url"],
                        "all_urls": v2_metadata["all_urls"],
                        "first_url_matches_snapshot": v2_metadata["first_url"] == v2_first_url,
                        "all_urls_match_snapshot": set(v2_metadata["all_urls"]) == v2_urls,
                    },
                },
            )

            # Log event counts and differences
            await logger.ainfo(
                "Total event count comparison",
                session_id=session_id,
                team_id=team_id,
                v1_snapshot_count=len(v1_snapshots),
                v2_snapshot_count=len(v2_snapshots),
                v1_metadata_count=v1_metadata["event_count"],
                v2_metadata_count=v2_metadata["event_count"],
                snapshot_difference=len(v2_snapshots) - len(v1_snapshots),
                metadata_difference=v2_metadata["event_count"] - v1_metadata["event_count"],
                snapshot_vs_metadata_v1_difference=len(v1_snapshots) - v1_metadata["event_count"],
                snapshot_vs_metadata_v2_difference=len(v2_snapshots) - v2_metadata["event_count"],
            )

            await logger.ainfo(
                "Click count comparison",
                session_id=session_id,
                team_id=team_id,
                v1_snapshot_count=v1_click_count,
                v2_snapshot_count=v2_click_count,
                v1_metadata_count=v1_metadata["click_count"],
                v2_metadata_count=v2_metadata["click_count"],
                snapshot_difference=v2_click_count - v1_click_count,
                metadata_difference=v2_metadata["click_count"] - v1_metadata["click_count"],
                snapshot_vs_metadata_v1_difference=v1_click_count - v1_metadata["click_count"],
                snapshot_vs_metadata_v2_difference=v2_click_count - v2_metadata["click_count"],
            )

            await logger.ainfo(
                "Mouse activity count comparison",
                session_id=session_id,
                team_id=team_id,
                v1_snapshot_count=v1_mouse_activity_count,
                v2_snapshot_count=v2_mouse_activity_count,
                v1_metadata_count=v1_metadata["mouse_activity_count"],
                v2_metadata_count=v2_metadata["mouse_activity_count"],
                snapshot_difference=v2_mouse_activity_count - v1_mouse_activity_count,
                metadata_difference=v2_metadata["mouse_activity_count"] - v1_metadata["mouse_activity_count"],
                snapshot_vs_metadata_v1_difference=v1_mouse_activity_count - v1_metadata["mouse_activity_count"],
                snapshot_vs_metadata_v2_difference=v2_mouse_activity_count - v2_metadata["mouse_activity_count"],
            )

            await logger.ainfo(
                "Keypress count comparison",
                session_id=session_id,
                team_id=team_id,
                v1_snapshot_count=v1_keypress_count,
                v2_snapshot_count=v2_keypress_count,
                v1_metadata_count=v1_metadata["keypress_count"],
                v2_metadata_count=v2_metadata["keypress_count"],
                snapshot_difference=v2_keypress_count - v1_keypress_count,
                metadata_difference=v2_metadata["keypress_count"] - v1_metadata["keypress_count"],
                snapshot_vs_metadata_v1_difference=v1_keypress_count - v1_metadata["keypress_count"],
                snapshot_vs_metadata_v2_difference=v2_keypress_count - v2_metadata["keypress_count"],
            )

            await logger.ainfo(
                "Console log count comparison",
                session_id=session_id,
                team_id=team_id,
                v1_snapshot_count=v1_console_log_count,
                v2_snapshot_count=v2_console_log_count,
                v1_metadata_count=v1_metadata["console_log_count"],
                v2_metadata_count=v2_metadata["console_log_count"],
                snapshot_difference=v2_console_log_count - v1_console_log_count,
                metadata_difference=v2_metadata["console_log_count"] - v1_metadata["console_log_count"],
                snapshot_vs_metadata_v1_difference=v1_console_log_count - v1_metadata["console_log_count"],
                snapshot_vs_metadata_v2_difference=v2_console_log_count - v2_metadata["console_log_count"],
            )

            await logger.ainfo(
                "Console warn count comparison",
                session_id=session_id,
                team_id=team_id,
                v1_snapshot_count=v1_console_warn_count,
                v2_snapshot_count=v2_console_warn_count,
                v1_metadata_count=v1_metadata["console_warn_count"],
                v2_metadata_count=v2_metadata["console_warn_count"],
                snapshot_difference=v2_console_warn_count - v1_console_warn_count,
                metadata_difference=v2_metadata["console_warn_count"] - v1_metadata["console_warn_count"],
                snapshot_vs_metadata_v1_difference=v1_console_warn_count - v1_metadata["console_warn_count"],
                snapshot_vs_metadata_v2_difference=v2_console_warn_count - v2_metadata["console_warn_count"],
            )

            await logger.ainfo(
                "Console error count comparison",
                session_id=session_id,
                team_id=team_id,
                v1_snapshot_count=v1_console_error_count,
                v2_snapshot_count=v2_console_error_count,
                v1_metadata_count=v1_metadata["console_error_count"],
                v2_metadata_count=v2_metadata["console_error_count"],
                snapshot_difference=v2_console_error_count - v1_console_error_count,
                metadata_difference=v2_metadata["console_error_count"] - v1_metadata["console_error_count"],
                snapshot_vs_metadata_v1_difference=v1_console_error_count - v1_metadata["console_error_count"],
                snapshot_vs_metadata_v2_difference=v2_console_error_count - v2_metadata["console_error_count"],
            )

            # Log event type comparison
            await logger.ainfo(
                "Event type comparison",
                session_id=session_id,
                team_id=team_id,
                common_events_count=sum(min(v1, v2) for v1, v2 in common_events.values()),
                common_events_by_type=group_events_by_type({k: min(v1, v2) for k, (v1, v2) in common_events.items()}),
                only_in_v1_count=sum(only_in_v1.values()),
                only_in_v1_by_type=group_events_by_type(only_in_v1),
                only_in_v2_count=sum(only_in_v2.values()),
                only_in_v2_by_type=group_events_by_type(only_in_v2),
                duplicate_stats={
                    "v1_total_duplicates": sum(count - 1 for count in v1_events.values() if count > 1),
                    "v2_total_duplicates": sum(count - 1 for count in v2_events.values() if count > 1),
                    "events_with_different_counts": {k: (v1, v2) for k, (v1, v2) in common_events.items() if v1 != v2},
                },
            )

            # Compare snapshot metadata
            await logger.ainfo(
                "Snapshot metadata comparison",
                session_id=session_id,
                team_id=team_id,
                v1_snapshot_source=v1_metadata["snapshot_source"],
                v2_snapshot_source=v2_metadata["snapshot_source"],
                v1_snapshot_library=v1_metadata["snapshot_library"],
                v2_snapshot_library=v2_metadata["snapshot_library"],
                snapshot_source_matches=v1_metadata["snapshot_source"] == v2_metadata["snapshot_source"],
                snapshot_library_matches=v1_metadata["snapshot_library"] == v2_metadata["snapshot_library"],
            )

            # Compare active milliseconds
            v1_computed_active_ms, v2_computed_active_ms = compute_active_milliseconds(v1_snapshots)
            v1_computed_active_ms_v2, v2_computed_active_ms_v2 = compute_active_milliseconds(v2_snapshots)

            # Calculate percentage differences
            def safe_percentage_diff(a: int, b: int) -> float:
                if a == 0 and b == 0:
                    return 0.0
                if a == 0:
                    return 100.0
                return ((b - a) / a) * 100

            await logger.ainfo(
                "Active milliseconds comparison",
                session_id=session_id,
                team_id=team_id,
                v1_snapshot_computed_v1_alg=v1_computed_active_ms,
                v2_snapshot_computed_v1_alg=v2_computed_active_ms,
                v1_snapshot_computed_v2_alg=v1_computed_active_ms_v2,
                v2_snapshot_computed_v2_alg=v2_computed_active_ms_v2,
                # Compare v1 vs v2 algorithms on v1 snapshots
                v1_snapshots_alg_difference=v1_computed_active_ms_v2 - v1_computed_active_ms,
                v1_snapshots_alg_difference_percentage=safe_percentage_diff(
                    v1_computed_active_ms, v1_computed_active_ms_v2
                ),
                # Compare v1 vs v2 algorithms on v2 snapshots
                v2_snapshots_alg_difference=v2_computed_active_ms_v2 - v2_computed_active_ms,
                v2_snapshots_alg_difference_percentage=safe_percentage_diff(
                    v2_computed_active_ms, v2_computed_active_ms_v2
                ),
                v1_metadata_value=v1_metadata["active_milliseconds"],
                v2_metadata_value=v2_metadata["active_milliseconds"],
                snapshot_difference_v1_alg=v2_computed_active_ms - v1_computed_active_ms,
                snapshot_difference_percentage_v1_alg=safe_percentage_diff(
                    v1_computed_active_ms, v2_computed_active_ms
                ),
                snapshot_difference_v2_alg=v2_computed_active_ms_v2 - v1_computed_active_ms_v2,
                snapshot_difference_percentage_v2_alg=safe_percentage_diff(
                    v1_computed_active_ms_v2, v2_computed_active_ms_v2
                ),
                metadata_difference=v2_metadata["active_milliseconds"] - v1_metadata["active_milliseconds"],
                metadata_difference_percentage=safe_percentage_diff(
                    v1_metadata["active_milliseconds"], v2_metadata["active_milliseconds"]
                ),
                v1_computed_vs_metadata_difference_v1_alg=v1_computed_active_ms - v1_metadata["active_milliseconds"],
                v1_computed_vs_metadata_percentage_v1_alg=safe_percentage_diff(
                    v1_metadata["active_milliseconds"], v1_computed_active_ms
                ),
                v2_computed_vs_metadata_difference_v1_alg=v2_computed_active_ms - v2_metadata["active_milliseconds"],
                v2_computed_vs_metadata_percentage_v1_alg=safe_percentage_diff(
                    v2_metadata["active_milliseconds"], v2_computed_active_ms
                ),
                v1_computed_vs_metadata_difference_v2_alg=v1_computed_active_ms_v2 - v1_metadata["active_milliseconds"],
                v1_computed_vs_metadata_percentage_v2_alg=safe_percentage_diff(
                    v1_metadata["active_milliseconds"], v1_computed_active_ms_v2
                ),
                v2_computed_vs_metadata_difference_v2_alg=v2_computed_active_ms_v2 - v2_metadata["active_milliseconds"],
                v2_computed_vs_metadata_percentage_v2_alg=safe_percentage_diff(
                    v2_metadata["active_milliseconds"], v2_computed_active_ms_v2
                ),
            )

            # Analyze events per window
            v1_window_counts = count_events_per_window(v1_events)
            v2_window_counts = count_events_per_window(v2_events)

            # Find all window IDs
            all_window_ids = set(v1_window_counts.keys()) | set(v2_window_counts.keys())
            window_comparison = []
            # Handle None first, then sort the rest
            sorted_window_ids = ([None] if None in all_window_ids else []) + sorted(
                id for id in all_window_ids if id is not None
            )
            for window_id in sorted_window_ids:
                window_comparison.append(
                    {
                        "window_id": window_id,
                        "v1_events": v1_window_counts.get(window_id, 0),
                        "v2_events": v2_window_counts.get(window_id, 0),
                    }
                )

            await logger.ainfo(
                "Events per window comparison",
                session_id=session_id,
                team_id=team_id,
                window_counts=window_comparison,
                total_windows=len(all_window_ids),
                windows_in_v1=len(v1_window_counts),
                windows_in_v2=len(v2_window_counts),
                windows_in_both=len(set(v1_window_counts.keys()) & set(v2_window_counts.keys())),
            )

            # Check for differences in metadata vs snapshots
            metadata_differences = any(
                [
                    v1_metadata["click_count"] != v1_click_count,
                    v1_metadata["mouse_activity_count"] != v1_mouse_activity_count,
                    v1_metadata["keypress_count"] != v1_keypress_count,
                    v1_metadata["console_log_count"] != v1_console_log_count,
                    v1_metadata["console_warn_count"] != v1_console_warn_count,
                    v1_metadata["console_error_count"] != v1_console_error_count,
                    v2_metadata["click_count"] != v2_click_count,
                    v2_metadata["mouse_activity_count"] != v2_mouse_activity_count,
                    v2_metadata["keypress_count"] != v2_keypress_count,
                    v2_metadata["console_log_count"] != v2_console_log_count,
                    v2_metadata["console_warn_count"] != v2_console_warn_count,
                    v2_metadata["console_error_count"] != v2_console_error_count,
                ]
            )

            # Check if sessions differ in any way
            sessions_differ = any(
                [
                    len(v1_snapshots) != len(v2_snapshots),
                    v1_click_count != v2_click_count,
                    v1_mouse_activity_count != v2_mouse_activity_count,
                    v1_keypress_count != v2_keypress_count,
                    v1_console_log_count != v2_console_log_count,
                    v1_console_warn_count != v2_console_warn_count,
                    v1_console_error_count != v2_console_error_count,
                    v1_urls != v2_urls,
                    v1_first_url != v2_first_url,
                    bool(only_in_v1),
                    bool(only_in_v2),
                ]
            )

            # Log session summary
            await logger.ainfo(
                "Session comparison summary",
                session_id=session_id,
                team_id=team_id,
                sessions_differ=sessions_differ,
                metadata_snapshot_differences=metadata_differences,
                v1_snapshot_count=len(v1_snapshots),
                v2_snapshot_count=len(v2_snapshots),
            )

        end_time = dt.datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Log activity summary
        await logger.ainfo(
            "Completed sampled events comparison activity",
            duration_seconds=duration,
            sessions_processed=len(session_ids),
        )


@dataclasses.dataclass(frozen=True)
class CompareSampledRecordingEventsWorkflowInputs:
    """Inputs for the recording events comparison workflow."""

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


@temporalio.workflow.defn(name="compare-sampled-recording-events")
class CompareSampledRecordingEventsWorkflow(PostHogWorkflow):
    """Workflow to compare recording events between v1 and v2 for sampled sessions."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.paused = False

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CompareSampledRecordingEventsWorkflowInputs:
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

        return CompareSampledRecordingEventsWorkflowInputs(
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
    async def run(self, inputs: CompareSampledRecordingEventsWorkflowInputs):
        """Run the comparison of recording events."""
        await temporalio.workflow.wait_condition(lambda: not self.paused)

        started_after = dt.datetime.fromisoformat(inputs.started_after)
        started_before = dt.datetime.fromisoformat(inputs.started_before)

        logger = get_internal_logger()
        workflow_start = dt.datetime.now()

        logger.info(
            "Starting sampled events comparison workflow",
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

            activity_inputs = CompareSampledRecordingEventsActivityInputs(
                started_after=window_start.isoformat(),
                started_before=window_end.isoformat(),
                sample_size=inputs.sample_size,
            )

            await temporalio.workflow.execute_activity(
                compare_sampled_recording_events_activity,
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
            "Completed sampled events comparison workflow",
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
