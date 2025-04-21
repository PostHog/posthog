import asyncio
import dataclasses
import datetime as dt
import gzip
import json
from typing import Any, cast

import temporalio.activity
import temporalio.common
import temporalio.workflow
from asgiref.sync import sync_to_async

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_internal_logger
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.storage import object_storage
from posthog.session_recordings.session_recording_v2_service import list_blocks
from posthog.storage.session_recording_v2_object_storage import client as v2_client
from posthog.clickhouse.client import sync_execute
from posthog.models import Team


def decompress_and_parse_gzipped_json(data: bytes) -> list[Any]:
    try:
        decompressed = gzip.decompress(data).decode("utf-8")
        return parse_jsonl_with_broken_newlines(decompressed)
    except Exception as e:
        # If decompression fails, try parsing as plain JSON
        # as some older recordings might not be compressed
        try:
            text = data.decode("utf-8")
            return parse_jsonl_with_broken_newlines(text)
        except Exception:
            raise e


def find_line_break(text: str, pos: int) -> str:
    """Find the line break sequence at the given position."""
    if text[pos : pos + 2] == "\r\n":
        return "\r\n"
    return "\n"


def parse_jsonl_with_broken_newlines(text: str) -> list[Any]:
    """Parse JSONL that might have broken newlines within JSON objects."""
    results = []
    buffer = ""
    pos = 0

    while pos < len(text):
        # Find next line break
        next_pos = text.find("\n", pos)
        if next_pos == -1:
            # No more line breaks, process remaining text
            line = text[pos:]
            if line.strip():
                buffer = f"{buffer}{line}" if buffer else line
            break

        # Get the line break sequence for this line
        line_break = find_line_break(text, next_pos - 1)
        line = text[pos : next_pos + (2 if line_break == "\r\n" else 1) - 1]

        if not line.strip():
            pos = next_pos + len(line_break)
            continue

        buffer = f"{buffer}{line_break}{line}" if buffer else line

        try:
            parsed = json.loads(buffer)
            results.append(parsed)
            buffer = ""  # Reset buffer after successful parse
        except json.JSONDecodeError:
            # If we can't parse, keep accumulating in buffer
            pass

        pos = next_pos + len(line_break)

    # Try to parse any remaining buffer
    if buffer:
        try:
            results.append(json.loads(buffer))
        except json.JSONDecodeError:
            pass  # Discard unparseable final buffer

    return results


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


def transform_v2_snapshot(raw_snapshot: list) -> dict:
    """Transform v2 snapshot format [windowId, serializedEvent] into {window_id, data} format."""
    if not isinstance(raw_snapshot, list) or len(raw_snapshot) != 2:
        raise ValueError("Invalid v2 snapshot format")

    window_id, event = raw_snapshot
    return {"window_id": window_id, "data": event}


def transform_v1_snapshots(snapshots: list[dict]) -> list[dict]:
    """Transform v1 snapshots from [{windowId, data: [event]}] to [{windowId, data: event}]."""
    flattened = []
    for snapshot in snapshots:
        window_id = snapshot.get("window_id")
        data_array = snapshot.get("data", [])
        if not isinstance(data_array, list):
            continue

        for event in data_array:
            flattened.append({"window_id": window_id, "data": event})
    return flattened


@temporalio.activity.defn
async def compare_recording_snapshots_activity(inputs: CompareRecordingSnapshotsActivityInputs) -> None:
    """Compare session recording snapshots between v1 and v2 for a specific session."""
    logger = get_internal_logger()
    start_time = dt.datetime.now()
    await logger.ainfo(
        "Starting snapshot comparison activity for session %s",
        inputs.session_id,
    )

    async with Heartbeater():
        team = await sync_to_async(Team.objects.get)(id=inputs.team_id)
        recording = await sync_to_async(SessionRecording.get_or_build)(session_id=inputs.session_id, team=team)

        # Get v1 snapshots
        v1_snapshots = []
        if recording.object_storage_path:
            blob_prefix = recording.object_storage_path
            blob_keys = object_storage.list_objects(cast(str, blob_prefix))
            if blob_keys:
                for full_key in blob_keys:
                    blob_key = full_key.replace(blob_prefix.rstrip("/") + "/", "")
                    file_key = f"{recording.object_storage_path}/{blob_key}"
                    snapshots_data = object_storage.read_bytes(file_key)
                    if snapshots_data:
                        raw_snapshots = decompress_and_parse_gzipped_json(snapshots_data)
                        v1_snapshots.extend(transform_v1_snapshots(raw_snapshots))
        else:
            # Try ingestion storage path
            blob_prefix = recording.build_blob_ingestion_storage_path()
            blob_keys = object_storage.list_objects(blob_prefix)
            if blob_keys:
                for full_key in blob_keys:
                    blob_key = full_key.replace(blob_prefix.rstrip("/") + "/", "")
                    file_key = f"{blob_prefix}/{blob_key}"
                    snapshots_data = object_storage.read_bytes(file_key)
                    if snapshots_data:
                        raw_snapshots = decompress_and_parse_gzipped_json(snapshots_data)
                        v1_snapshots.extend(transform_v1_snapshots(raw_snapshots))

        # Get v2 snapshots
        v2_snapshots: list[dict[str, Any]] = []
        blocks = list_blocks(recording)
        if blocks:
            for block in blocks:
                try:
                    decompressed_block = v2_client().fetch_block(block["url"])
                    if decompressed_block:
                        # Parse the block using the same line parsing logic as v1
                        raw_snapshots = parse_jsonl_with_broken_newlines(decompressed_block)
                        # Transform each snapshot to match v1 format
                        v2_snapshots.extend(transform_v2_snapshot(snapshot) for snapshot in raw_snapshots)
                except Exception as e:
                    await logger.aexception("Failed to fetch v2 block", exception=e)

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
        def get_metadata_counts(team_id: int, session_id: str, table_name: str) -> dict[str, int]:
            query = f"""
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
                FROM {table_name}
                WHERE team_id = %(team_id)s
                AND session_id = %(session_id)s
                GROUP BY session_id, team_id
                LIMIT 1
            """
            result = sync_execute(
                query,
                {
                    "team_id": team_id,
                    "session_id": session_id,
                },
            )
            if not result:
                return {
                    "click_count": 0,
                    "mouse_activity_count": 0,
                    "keypress_count": 0,
                    "event_count": 0,
                    "console_log_count": 0,
                    "console_warn_count": 0,
                    "console_error_count": 0,
                    "first_url": None,
                    "all_urls": [],
                }

            row = result[0]
            return {
                "click_count": row[7],  # click_count index
                "keypress_count": row[8],  # keypress_count index
                "mouse_activity_count": row[9],  # mouse_activity_count index
                "console_log_count": row[11],  # console_log_count index
                "console_warn_count": row[12],  # console_warn_count index
                "console_error_count": row[13],  # console_error_count index
                "event_count": row[14],  # event_count index
                "first_url": row[5],  # first_url index
                "all_urls": row[6],  # all_urls index
            }

        v1_metadata = get_metadata_counts(team.pk, recording.session_id, "session_replay_events")
        v2_metadata = get_metadata_counts(team.pk, recording.session_id, "session_replay_events_v2_test")

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

        # Log structure of first snapshot from each version
        if v1_snapshots:
            await logger.ainfo("V1 snapshot structure", structure=_get_structure(v1_snapshots))
        if v2_snapshots:
            await logger.ainfo("V2 snapshot structure", structure=_get_structure(v2_snapshots))

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
        def count_events_per_window(events: dict[str, int]) -> dict[str | None, int]:
            window_counts: dict[str | None, int] = {}
            for event_json, count in events.items():
                window_id, _ = json.loads(event_json)
                # Convert "null" string to None if needed (in case of JSON serialization)
                if isinstance(window_id, str) and window_id.lower() == "null":
                    window_id = None
                window_counts[window_id] = window_counts.get(window_id, 0) + count
            return window_counts

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

        # Sample differing events
        def find_differences(obj1: Any, obj2: Any, path: str = "$") -> list[dict[str, Any]]:
            """
            Recursively compare two objects and return list of differences with jq-style paths.
            Example paths: $.key, $.array[0], $.nested.key, etc.
            """
            differences = []

            if type(obj1) is not type(obj2):
                differences.append(
                    {
                        "path": path,
                        "type": "type_mismatch",
                        "v1_type": type(obj1).__name__,
                        "v2_type": type(obj2).__name__,
                        "v1_value": obj1,
                        "v2_value": obj2,
                    }
                )
                return differences

            if isinstance(obj1, dict):
                all_keys = set(obj1.keys()) | set(obj2.keys())
                for key in all_keys:
                    key_path = f"{path}.{key}"
                    if key not in obj1:
                        differences.append(
                            {
                                "path": key_path,
                                "type": "key_missing_in_v1",
                                "v2_value": obj2[key],
                            }
                        )
                    elif key not in obj2:
                        differences.append(
                            {
                                "path": key_path,
                                "type": "key_missing_in_v2",
                                "v1_value": obj1[key],
                            }
                        )
                    else:
                        differences.extend(find_differences(obj1[key], obj2[key], key_path))

            elif isinstance(obj1, list):
                if len(obj1) != len(obj2):
                    differences.append(
                        {
                            "path": path,
                            "type": "array_length_mismatch",
                            "v1_length": len(obj1),
                            "v2_length": len(obj2),
                        }
                    )
                for i, (item1, item2) in enumerate(zip(obj1, obj2)):
                    differences.extend(find_differences(item1, item2, f"{path}[{i}]"))

            elif obj1 != obj2:
                differences.append(
                    {
                        "path": path,
                        "type": "value_mismatch",
                        "v1_value": obj1,
                        "v2_value": obj2,
                    }
                )

            return differences

        # def sample_events(events: dict[str, int], size: int) -> list[tuple[str, dict, list[dict]]]:
        #     """Sample events and include their differences."""
        #     samples = []
        #     for event_json, _ in list(events.items())[:size]:
        #         window_id, data = json.loads(event_json)
        #         # Try to find matching event in other version by window_id
        #         matching_event = None
        #         if event_json in only_in_v1:
        #             # Look for matching window_id in v2
        #             for v2_json, _ in v2_events.items():
        #                 v2_window_id, v2_data = json.loads(v2_json)
        #                 if v2_window_id == window_id:
        #                     matching_event = v2_data
        #                     break
        #         else:
        #             # Look for matching window_id in v1
        #             for v1_json, _ in v1_events.items():
        #                 v1_window_id, v1_data = json.loads(v1_json)
        #                 if v1_window_id == window_id:
        #                     matching_event = v1_data
        #                     break

        #         differences = []
        #         if matching_event:
        #             differences = find_differences(data, matching_event)

        #         samples.append((window_id, data, differences))
        #     return samples

        # await logger.ainfo(
        #     "Sample of differing events",
        #     v1_exclusive_samples=[(window_id, str(data)[:100], differences) for window_id, data, differences in sample_events(only_in_v1, inputs.sample_size)],
        #     v2_exclusive_samples=[(window_id, str(data)[:100], differences) for window_id, data, differences in sample_events(only_in_v2, inputs.sample_size)],
        # )

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


def _get_structure(obj: Any, max_depth: int = 10) -> Any:
    """Get the structure of an object without its values."""
    if max_depth <= 0:
        return "..."

    if isinstance(obj, dict):
        return {k: _get_structure(v, max_depth - 1) for k, v in obj.items()}
    elif isinstance(obj, list):
        if not obj:
            return []
        # Just show structure of first item for arrays
        return [_get_structure(obj[0], max_depth - 1)]
    elif isinstance(obj, str | int | float | bool):
        return type(obj).__name__
    elif obj is None:
        return None
    return type(obj).__name__


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
