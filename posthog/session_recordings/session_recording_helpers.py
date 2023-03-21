import base64
import dataclasses
import gzip
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, DefaultDict, Dict, Generator, List, Optional, cast

from sentry_sdk.api import capture_exception, capture_message

from posthog.models import utils
from posthog.models.session_recording.metadata import (
    DecompressedRecordingData,
    DecompressedSnapshotDataEventsSummary,
    RecordingMetadata,
    RecordingSegment,
    SessionRecordingEventSummary,
    SnapshotData,
    SnapshotDataTaggedWithWindowId,
    WindowId,
)
from posthog.utils import flatten

FULL_SNAPSHOT = 2


# NOTE: For reference here are some helpful enum mappings from rrweb
# https://github.com/rrweb-io/rrweb/blob/master/packages/rrweb/src/types.ts

# event.type


class RRWEB_MAP_EVENT_TYPE:
    DomContentLoaded = 0
    Load = 1
    FullSnapshot = 2
    IncrementalSnapshot = 3
    Meta = 4
    Custom = 5
    Plugin = 6


# event.data.source
class RRWEB_MAP_EVENT_DATA_SOURCE:
    Mutation = 0
    MouseMove = 1
    MouseInteraction = 2
    Scroll = 3
    ViewportResize = 4
    Input = 5
    TouchMove = 6
    MediaInteraction = 7
    StyleSheetRule = 8
    CanvasMutation = 9
    Font = 1
    Log = 1
    Drag = 1
    StyleDeclaration = 1
    Selection = 1


# event.data.type
class RRWEB_MAP_EVENT_DATA_TYPE:
    MouseUp = 0
    MouseDown = 1
    Click = 2
    ContextMenu = 3
    DblClick = 4
    Focus = 5
    Blur = 6
    TouchStart = 7
    TouchMove_Departed = 8
    TouchEnd = 9
    TouchCancel = 10


# List of properties from the event payload we care about for our uncompressed `events_summary`
# NOTE: We should keep this as minimal as possible
EVENT_SUMMARY_DATA_INCLUSIONS = [
    "type",
    "source",
    "tag",
    "plugin",
    "href",
    "width",
    "height",
    "payload.href",
    "payload.level",
]


Event = Dict[str, Any]


def preprocess_session_recording_events_for_clickhouse(events: List[Event]) -> List[Event]:
    result = []
    snapshots_by_session_and_window_id = defaultdict(list)
    for event in events:
        if is_unchunked_snapshot(event):
            session_id = event["properties"]["$session_id"]
            window_id = event["properties"].get("$window_id")
            snapshots_by_session_and_window_id[(session_id, window_id)].append(event)
        else:
            result.append(event)

    for _, snapshots in snapshots_by_session_and_window_id.items():
        result.extend(list(compress_and_chunk_snapshots(snapshots)))

    return result


def compress_and_chunk_snapshots(events: List[Event], chunk_size=512 * 1024) -> Generator[Event, None, None]:
    data_list = [event["properties"]["$snapshot_data"] for event in events]
    session_id = events[0]["properties"]["$session_id"]
    has_full_snapshot = any(snapshot_data["type"] == RRWEB_MAP_EVENT_TYPE.FullSnapshot for snapshot_data in data_list)
    window_id = events[0]["properties"].get("$window_id")

    compressed_data = compress_to_string(json.dumps(data_list))

    id = str(utils.UUIDT())
    chunks = chunk_string(compressed_data, chunk_size)

    for index, chunk in enumerate(chunks):
        yield {
            **events[0],
            "properties": {
                **events[0]["properties"],
                "$session_id": session_id,
                "$window_id": window_id,
                # If it is the first chunk we include all events
                "$snapshot_data": {
                    "chunk_id": id,
                    "chunk_index": index,
                    "chunk_count": len(chunks),
                    "data": chunk,
                    "compression": "gzip-base64",
                    "has_full_snapshot": has_full_snapshot,
                    # We only store this field on the first chunk as it contains all events, not just this chunk
                    "events_summary": get_events_summary_from_snapshot_data(data_list) if index == 0 else None,
                },
            },
        }


def chunk_string(string: str, chunk_length: int) -> List[str]:
    """Split a string into chunk_length-sized elements. Reversal operation: `''.join()`."""
    return [string[0 + offset : chunk_length + offset] for offset in range(0, len(string), chunk_length)]


def is_unchunked_snapshot(event: Dict) -> bool:
    try:
        is_snapshot = event["event"] == "$snapshot"
    except KeyError:
        raise ValueError('All events must have the event name field "event"!')
    except TypeError:
        raise ValueError(f"All events must be dictionaries not '{type(event).__name__}'!")
    try:
        return is_snapshot and "chunk_id" not in event["properties"]["$snapshot_data"]
    except KeyError:
        capture_exception()
        raise ValueError('$snapshot events must contain property "$snapshot_data"!')


def compress_to_string(json_string: str) -> str:
    compressed_data = gzip.compress(json_string.encode("utf-16", "surrogatepass"))
    return base64.b64encode(compressed_data).decode("utf-8")


def decompress(base64data: str) -> str:
    compressed_bytes = base64.b64decode(base64data)
    return gzip.decompress(compressed_bytes).decode("utf-16", "surrogatepass")


def decompress_chunked_snapshot_data(
    team_id: int,
    session_recording_id: str,
    all_recording_events: List[SnapshotDataTaggedWithWindowId],
    limit: Optional[int] = None,
    offset: int = 0,
    return_only_activity_data: bool = False,
) -> DecompressedRecordingData:
    """
    Before data is stored in clickhouse, it is compressed and then chunked. This function
    gets back to the original data by unchunking the events and then decompressing the data.

    If limit + offset is provided, then it will paginate the decompression by chunks (not by events, because
    you can't decompress an incomplete chunk).

    Depending on the size of the recording, this function can return a lot of data. To decrease the
    memory used, you should either use the pagination parameters or pass in 'return_only_activity_data' which
    drastically reduces the size of the data returned if you only want the activity data (used for metadata calculation)
    """

    if len(all_recording_events) == 0:
        return DecompressedRecordingData(has_next=False, snapshot_data_by_window_id={})

    snapshot_data_by_window_id: DecompressedSnapshotDataEventsSummary = {}

    # Split decompressed recording events into their chunks
    chunks_collector: DefaultDict[str, List[SnapshotDataTaggedWithWindowId]] = defaultdict(list)
    for event in all_recording_events:
        chunks_collector[event["snapshot_data"]["chunk_id"]].append(event)

    # Paginate the list of chunks
    paginated_chunk_list = paginate_list(list(chunks_collector.values()), limit, offset)

    has_next = paginated_chunk_list.has_next
    chunk_list: List[List[SnapshotDataTaggedWithWindowId]] = paginated_chunk_list.paginated_list

    # Decompress the chunks and split the resulting events by window_id
    for chunks in chunk_list:
        if len(chunks) != chunks[0]["snapshot_data"]["chunk_count"]:
            capture_message(
                "Did not find all session recording chunks! Team: {}, Session: {}, Chunk-id: {}. Found {} of {} expected chunks".format(
                    team_id,
                    session_recording_id,
                    chunks[0]["snapshot_data"]["chunk_id"],
                    len(chunks),
                    chunks[0]["snapshot_data"]["chunk_count"],
                )
            )
            continue

        b64_compressed_data = "".join(
            chunk["snapshot_data"]["data"] for chunk in sorted(chunks, key=lambda c: c["snapshot_data"]["chunk_index"])
        )
        decompressed_data = json.loads(decompress(b64_compressed_data))

        events_summary = flatten(
            [
                chunk["snapshot_data"]["events_summary"]
                for chunk in sorted(chunks, key=lambda c: c["snapshot_data"]["chunk_index"])
            ]
        )

        if chunks[0]["window_id"] not in snapshot_data_by_window_id:
            snapshot_data_by_window_id[chunks[0]["window_id"]] = {"events_summary": [], "snapshot_data": []}

        # Include materialized events summary to keep this consistent with metadata endpoint
        snapshot_data_by_window_id[chunks[0]["window_id"]]["events_summary"].extend(events_summary)

        # Decompressed data can be large, and in metadata calculations, we only care if the event is "active"
        # This pares down the data returned, so we're not passing around a massive object
        if return_only_activity_data:
            events_with_only_activity_data = get_events_summary_from_snapshot_data(decompressed_data)
            snapshot_data_by_window_id[chunks[0]["window_id"]]["snapshot_data"].extend(events_with_only_activity_data)
        else:
            snapshot_data_by_window_id[chunks[0]["window_id"]]["snapshot_data"].extend(decompressed_data)

        for window_id in snapshot_data_by_window_id.keys():
            snapshot_data_by_window_id[window_id]["snapshot_data"].sort(key=lambda x: x["timestamp"])
            snapshot_data_by_window_id[window_id]["events_summary"].sort(key=lambda x: x["timestamp"])
    return DecompressedRecordingData(has_next=has_next, snapshot_data_by_window_id=snapshot_data_by_window_id)


def is_active_event(event: SessionRecordingEventSummary) -> bool:
    """
    Determines which rr-web events are "active" - meaning user generated
    """
    active_rr_web_sources = [
        1,  # MouseMove,
        2,  # MouseInteraction,
        3,  # Scroll,
        4,  # ViewportResize,
        5,  # Input,
        6,  # TouchMove,
        7,  # MediaInteraction,
        12,  # Drag,
    ]
    return event["type"] == 3 and event["data"].get("source") in active_rr_web_sources


def parse_snapshot_timestamp(timestamp: int):
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc)


ACTIVITY_THRESHOLD_SECONDS = 10


def get_active_segments_from_event_list(
    event_list: List[SessionRecordingEventSummary],
    window_id: WindowId,
    activity_threshold_seconds=ACTIVITY_THRESHOLD_SECONDS,
) -> List[RecordingSegment]:
    """
    Processes a list of events for a specific window_id to determine
    the segments of the recording where the user is "active". And active segment ends
    when there isn't another active event for activity_threshold_seconds seconds
    """
    active_event_timestamps = [event["timestamp"] for event in event_list if is_active_event(event)]

    active_recording_segments: List[RecordingSegment] = []
    current_active_segment: Optional[RecordingSegment] = None
    for current_timestamp_int in active_event_timestamps:
        current_timestamp = parse_snapshot_timestamp(current_timestamp_int)
        # If the time since the last active event is less than the threshold, continue the existing segment
        if current_active_segment and (current_timestamp - current_active_segment["end_time"]) <= timedelta(
            seconds=activity_threshold_seconds
        ):
            current_active_segment["end_time"] = current_timestamp

        # Otherwise, start a new segment
        else:
            if current_active_segment:
                active_recording_segments.append(current_active_segment)
            current_active_segment = RecordingSegment(
                start_time=current_timestamp, end_time=current_timestamp, window_id=window_id, is_active=True
            )

    # Add the active last segment if it hasn't already been added
    if current_active_segment and (
        len(active_recording_segments) == 0 or active_recording_segments[-1] != current_active_segment
    ):
        active_recording_segments.append(current_active_segment)

    return active_recording_segments


def get_events_summary_from_snapshot_data(snapshot_data: List[SnapshotData]) -> List[SessionRecordingEventSummary]:
    """
    Extract a minimal representation of the snapshot data events for easier querying.
    'data' and 'data.payload' values are included as long as they are strings or numbers
    and in the inclusion list to keep the payload minimal
    """
    events_summary = []

    for event in snapshot_data:
        if "timestamp" not in event or "type" not in event:
            continue

        # Get all top level data values
        data = {
            key: value
            for key, value in event.get("data", {}).items()
            if type(value) in [str, int] and key in EVENT_SUMMARY_DATA_INCLUSIONS
        }
        # Some events have a payload, some values of which we want
        if event.get("data", {}).get("payload"):
            # Make sure the payload is a dict before we access it
            if isinstance(event["data"]["payload"], dict):
                data["payload"] = {
                    key: value
                    for key, value in event["data"]["payload"].items()
                    if type(value) in [str, int] and f"payload.{key}" in EVENT_SUMMARY_DATA_INCLUSIONS
                }

        events_summary.append(
            SessionRecordingEventSummary(
                timestamp=event["timestamp"],
                type=event["type"],
                data=data,
            )
        )

    # No guarantees are made about order so we sort here to be sure
    events_summary.sort(key=lambda x: x["timestamp"])

    return events_summary


@dataclasses.dataclass
class PaginatedList:
    has_next: bool
    paginated_list: List


def paginate_list(list_to_paginate: List, limit: Optional[int], offset: int) -> PaginatedList:
    if not limit:
        has_next = False
        paginated_list = list_to_paginate[offset:]
    elif offset + limit < len(list_to_paginate):
        has_next = True
        paginated_list = list_to_paginate[offset : offset + limit]
    else:
        has_next = False
        paginated_list = list_to_paginate[offset:]
    return PaginatedList(has_next=has_next, paginated_list=paginated_list)


def get_metadata_from_events_summary(
    events_summary_by_window_id: Dict[WindowId, List[SessionRecordingEventSummary]]
) -> RecordingMetadata:
    """
    This function processes the recording events into metadata.

    A recording can be composed of events from multiple windows/tabs. Recording events are seperated by
    `window_id`, so the playback experience is consistent (changes in one tab don't impact the recording
    of a different tab). However, we still want to playback the recording to the end user as the user interacted
    with their product.

    This function creates a "playlist" of recording segments that designates the order in which the front end
    should flip between players of different windows/tabs. To create this playlist, this function does the following:

    (1) For each recording event, we determine if it is "active" or not. An active event designates user
    activity (e.g. mouse movement).

    (2) We then generate "active segments" based on these lists of events. Active segments are segments
    of recordings where the maximum time between events determined to be active is less than a threshold (set to 60 seconds).

    (3) Next, we merge the active segments from all of the window_ids + sort them by start time. We now have the
    list of active segments. (note, it's very possible that active segments overlap if a user is flipping back
    and forth between tabs)

    (4) [THIS STEP WAS MOVED TO THE FRONTEND] See `recordingDataUtils.ts` To complete the recording, we fill in the gaps
    between active segments with "inactive segments". In determining which window should be used for the inactive segment,
    we try to minimize the switching of windows.
    """

    start_and_end_times_by_window_id: Dict[WindowId, RecordingSegment] = {}

    # Get the active segments for each window_id
    all_active_segments: List[RecordingSegment] = []

    for window_id, events_summary in events_summary_by_window_id.items():
        active_segments_for_window_id = get_active_segments_from_event_list(events_summary, window_id)

        all_active_segments.extend(active_segments_for_window_id)

        start_and_end_times_by_window_id[window_id] = RecordingSegment(
            window_id=window_id,
            start_time=parse_snapshot_timestamp(events_summary[0]["timestamp"]),
            end_time=parse_snapshot_timestamp(events_summary[-1]["timestamp"]),
            is_active=False,  # We don't know yet
        )

    # Sort the active segments by start time. This will interleave active segments
    # from different windows
    all_active_segments.sort(key=lambda segment: segment["start_time"])

    # These start and end times are used to make sure the segments span the entire recording
    first_start_time = min([cast(datetime, x["start_time"]) for x in start_and_end_times_by_window_id.values()])
    last_end_time = max([cast(datetime, x["end_time"]) for x in start_and_end_times_by_window_id.values()])

    all_events_summary: List[SessionRecordingEventSummary] = list(flatten(list(events_summary_by_window_id.values())))

    click_count = len([x for x in all_events_summary if x["type"] == 3 and x["data"]["source"] == 2])
    keypress_count = len([x for x in all_events_summary if x["type"] == 3 and x["data"]["source"] == 5])
    urls: List[str] = [
        cast(str, x["data"]["href"]) for x in all_events_summary if isinstance(x.get("data", {}).get("href"), str)
    ]

    return RecordingMetadata(
        distinct_id="",  # Will be added by the caller
        segments=all_active_segments,
        start_and_end_times_by_window_id=start_and_end_times_by_window_id,
        start_time=first_start_time,
        end_time=last_end_time,
        duration=(last_end_time - first_start_time).seconds,
        click_count=click_count,
        keypress_count=keypress_count,
        urls=urls,
    )
