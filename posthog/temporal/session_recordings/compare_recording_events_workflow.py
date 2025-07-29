import asyncio
import dataclasses
import datetime as dt
import json
from typing import Any

import temporalio.activity
import temporalio.common
import temporalio.workflow
from asgiref.sync import sync_to_async

from posthog.clickhouse.query_tagging import tag_queries, Product
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_internal_logger
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.models import Team
from posthog.temporal.session_recordings.queries import get_session_metadata
from posthog.temporal.session_recordings.snapshot_utils import fetch_v1_snapshots, fetch_v2_snapshots
from posthog.temporal.session_recordings.session_comparer import count_events_per_window
from posthog.temporal.session_recordings.segmentation import compute_active_milliseconds


@dataclasses.dataclass(frozen=True)
class CompareRecordingSnapshotsActivityInputs:
    """Inputs for the `compare_recording_snapshots_activity`."""

    session_id: str = dataclasses.field()
    team_id: int = dataclasses.field()
    sample_size: int = dataclasses.field(default=5)

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "team_id": self.team_id,
            "sample_size": self.sample_size,
        }


@temporalio.activity.defn
async def compare_recording_snapshots_activity(inputs: CompareRecordingSnapshotsActivityInputs) -> None:
    """Compare session recording snapshots between v1 and v2 for a specific session."""
    logger = get_internal_logger()
    start_time = dt.datetime.now()
    await logger.ainfo(
        "Starting snapshot comparison activity for session %s",
        inputs.session_id,
    )
    tag_queries(team_id=inputs.team_id, product=Product.REPLAY)

    async with Heartbeater():
        team = await sync_to_async(Team.objects.get)(id=inputs.team_id)
        recording = await sync_to_async(SessionRecording.get_or_build)(session_id=inputs.session_id, team=team)

        # Get v1 and v2 snapshots using the shared utility functions
        v1_snapshots = await asyncio.to_thread(fetch_v1_snapshots, recording)
        v2_snapshots = await asyncio.to_thread(fetch_v2_snapshots, recording)

        # Compare snapshots
        snapshot_differences = []
        v1_click_count = 0
        v2_click_count = 0

        def is_click(event: dict) -> bool:
            CLICK_TYPES = [2, 4, 9, 3]  # Click, DblClick, TouchEnd, ContextMenu
            return (
                event.get("type") == 3  # RRWebEventType.IncrementalSnapshot
                and event.get("data", {}).get("source") == 2  # RRWebEventSource.MouseInteraction
                and event.get("data", {}).get("type") in CLICK_TYPES
            )

        def is_mouse_activity(event: dict) -> bool:
            MOUSE_ACTIVITY_SOURCES = [2, 1, 6]  # MouseInteraction, MouseMove, TouchMove
            return (
                event.get("type") == 3  # RRWebEventType.IncrementalSnapshot
                and event.get("data", {}).get("source") in MOUSE_ACTIVITY_SOURCES
            )

        def is_keypress(event: dict) -> bool:
            return (
                event.get("type") == 3  # RRWebEventType.IncrementalSnapshot
                and event.get("data", {}).get("source") == 5  # RRWebEventSource.Input
            )

        def is_console_log(event: dict) -> bool:
            return (
                event.get("type") == 6  # RRWebEventType.Plugin
                and event.get("data", {}).get("plugin") == "rrweb/console@1"
            )

        def get_console_level(event: dict) -> str | None:
            if not is_console_log(event):
                return None
            return event.get("data", {}).get("payload", {}).get("level")

        def get_url_from_event(event: dict) -> str | None:
            """Extract URL from event using same logic as hrefFrom in rrweb-types.ts."""
            data = event.get("data", {})
            if not isinstance(data, dict):
                return None

            meta_href = data.get("href", "")
            meta_href = meta_href.strip() if isinstance(meta_href, str) else ""

            payload = data.get("payload", {})
            payload_href = payload.get("href", "") if isinstance(payload, dict) else ""
            payload_href = payload_href.strip() if isinstance(payload_href, str) else ""

            return meta_href or payload_href or None

        # Track URLs for both versions
        v1_urls: set[str] = set()
        v1_first_url: str | None = None
        v2_urls: set[str] = set()
        v2_first_url: str | None = None

        # Constants from snappy-session-recorder.ts
        MAX_URL_LENGTH = 4 * 1024  # 4KB
        MAX_URLS_COUNT = 25

        def add_url(url_set: set[str], url: str) -> None:
            """Add URL to set with same constraints as snappy-session-recorder.ts."""
            if not url:
                return
            if len(url) > MAX_URL_LENGTH:
                url = url[:MAX_URL_LENGTH]
            if len(url_set) < MAX_URLS_COUNT:
                url_set.add(url)

        # Count clicks, mouse activity, keypresses, and console logs in v1
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
                    v1_first_url = url[:MAX_URL_LENGTH] if len(url) > MAX_URL_LENGTH else url
                add_url(v1_urls, url)

        # Count clicks, mouse activity, keypresses, and console logs in v2
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
                    v2_first_url = url[:MAX_URL_LENGTH] if len(url) > MAX_URL_LENGTH else url
                add_url(v2_urls, url)

        # Get metadata counts
        v1_metadata = get_session_metadata(team.pk, recording.session_id, "session_replay_events")
        v2_metadata = get_session_metadata(team.pk, recording.session_id, "session_replay_events_v2_test")

        # Compare URLs
        await logger.ainfo(
            "URL comparison",
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

        await logger.ainfo(
            "Total event count comparison",
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
            v1_snapshot_count=v1_console_error_count,
            v2_snapshot_count=v2_console_error_count,
            v1_metadata_count=v1_metadata["console_error_count"],
            v2_metadata_count=v2_metadata["console_error_count"],
            snapshot_difference=v2_console_error_count - v1_console_error_count,
            metadata_difference=v2_metadata["console_error_count"] - v1_metadata["console_error_count"],
            snapshot_vs_metadata_v1_difference=v1_console_error_count - v1_metadata["console_error_count"],
            snapshot_vs_metadata_v2_difference=v2_console_error_count - v2_metadata["console_error_count"],
        )

        # Compare total count
        if len(v1_snapshots) != len(v2_snapshots):
            snapshot_differences.append(
                {
                    "type": "count_mismatch",
                    "v1_count": len(v1_snapshots),
                    "v2_count": len(v2_snapshots),
                }
            )

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

        # Group events by type
        def get_event_type(event_json: str) -> str:
            _, data = json.loads(event_json)
            return data.get("type", "unknown")

        def group_events_by_type(events: dict[str, int]) -> dict[str, int]:
            type_counts: dict[str, int] = {}
            for event, count in events.items():
                event_type = get_event_type(event)
                type_counts[event_type] = type_counts.get(event_type, 0) + count
            return type_counts

        v1_exclusive_by_type = group_events_by_type(only_in_v1)
        v2_exclusive_by_type = group_events_by_type(only_in_v2)
        # For common events, sum up the minimum count between v1 and v2 for each event
        common_by_type = group_events_by_type({k: min(v1, v2) for k, (v1, v2) in common_events.items()})

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
            window_counts=window_comparison,
            total_windows=len(all_window_ids),
            windows_in_v1=len(v1_window_counts),
            windows_in_v2=len(v2_window_counts),
            windows_in_both=len(set(v1_window_counts.keys()) & set(v2_window_counts.keys())),
        )

        await logger.ainfo(
            "Event type comparison",
            common_events_count=sum(min(v1, v2) for v1, v2 in common_events.values()),
            common_events_by_type=common_by_type,
            only_in_v1_count=sum(only_in_v1.values()),
            only_in_v1_by_type=v1_exclusive_by_type,
            only_in_v2_count=sum(only_in_v2.values()),
            only_in_v2_by_type=v2_exclusive_by_type,
            duplicate_stats={
                "v1_total_duplicates": sum(count - 1 for count in v1_events.values() if count > 1),
                "v2_total_duplicates": sum(count - 1 for count in v2_events.values() if count > 1),
                "events_with_different_counts": {k: (v1, v2) for k, (v1, v2) in common_events.items() if v1 != v2},
            },
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
            snapshot_difference_percentage_v1_alg=safe_percentage_diff(v1_computed_active_ms, v2_computed_active_ms),
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

        # Compare snapshot metadata
        await logger.ainfo(
            "Snapshot metadata comparison",
            v1_snapshot_source=v1_metadata["snapshot_source"],
            v2_snapshot_source=v2_metadata["snapshot_source"],
            v1_snapshot_library=v1_metadata["snapshot_library"],
            v2_snapshot_library=v2_metadata["snapshot_library"],
            snapshot_source_matches=v1_metadata["snapshot_source"] == v2_metadata["snapshot_source"],
            snapshot_library_matches=v1_metadata["snapshot_library"] == v2_metadata["snapshot_library"],
        )

        end_time = dt.datetime.now()
        duration = (end_time - start_time).total_seconds()

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

        # Log summary
        await logger.ainfo(
            "Completed snapshot comparison activity",
            duration_seconds=duration,
            session_id=inputs.session_id,
            v1_snapshot_count=len(v1_snapshots),
            v2_snapshot_count=len(v2_snapshots),
            sessions_differ=sessions_differ,
            metadata_snapshot_differences=metadata_differences,
        )


@dataclasses.dataclass(frozen=True)
class CompareRecordingSnapshotsWorkflowInputs:
    """Inputs for the `CompareRecordingSnapshotsWorkflow`."""

    session_id: str = dataclasses.field()
    team_id: int = dataclasses.field()

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "team_id": self.team_id,
        }


@temporalio.workflow.defn(name="compare-recording-snapshots")
class CompareRecordingSnapshotsWorkflow(PostHogWorkflow):
    """Workflow to compare session recording snapshots between v1 and v2."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.paused = False

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CompareRecordingSnapshotsWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])

        if "session_id" not in loaded:
            raise ValueError("Required field session_id not provided")
        if "team_id" not in loaded:
            raise ValueError("Required field team_id not provided")

        return CompareRecordingSnapshotsWorkflowInputs(
            session_id=loaded["session_id"],
            team_id=loaded["team_id"],
        )

    @temporalio.workflow.run
    async def run(self, inputs: CompareRecordingSnapshotsWorkflowInputs):
        """Run the comparison of session recording snapshots."""
        await temporalio.workflow.wait_condition(lambda: not self.paused)

        logger = get_internal_logger()
        workflow_start = dt.datetime.now()
        logger.info(
            "Starting snapshot comparison workflow for session %s",
            inputs.session_id,
        )

        activity_inputs = CompareRecordingSnapshotsActivityInputs(
            session_id=inputs.session_id,
            team_id=inputs.team_id,
        )

        await temporalio.workflow.execute_activity(
            compare_recording_snapshots_activity,
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
            "Completed snapshot comparison workflow in %.2f seconds",
            duration,
        )

    @temporalio.workflow.update
    async def pause(self) -> None:
        """Signal handler for workflow to pause or unpause."""
        async with self.lock:
            if self.paused is True:
                self.paused = False
            else:
                self.paused = True
