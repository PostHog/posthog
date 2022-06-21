import base64
import dataclasses
import gzip
import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import DefaultDict, Dict, Generator, List, Optional

from sentry_sdk.api import capture_exception, capture_message

from posthog.models import utils

FULL_SNAPSHOT = 2

Event = Dict
SnapshotData = Dict
WindowId = Optional[str]


@dataclasses.dataclass
class EventActivityData:
    timestamp: datetime
    is_active: bool


@dataclasses.dataclass
class RecordingSegment:
    start_time: datetime
    end_time: datetime
    window_id: WindowId
    is_active: bool

    def to_dict(self) -> Dict:
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "window_id": self.window_id,
            "is_active": self.is_active,
        }


@dataclasses.dataclass
class SnapshotDataTaggedWithWindowId:
    window_id: WindowId
    snapshot_data: SnapshotData


@dataclasses.dataclass
class DecompressedRecordingData:
    has_next: bool
    snapshot_data_by_window_id: Dict[WindowId, List[SnapshotData]]


def preprocess_session_recording_events(events: List[Event]) -> List[Event]:
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
    has_full_snapshot = any(snapshot_data["type"] == FULL_SNAPSHOT for snapshot_data in data_list)
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
                "$snapshot_data": {
                    "chunk_id": id,
                    "chunk_index": index,
                    "chunk_count": len(chunks),
                    "data": chunk,
                    "compression": "gzip-base64",
                    "has_full_snapshot": has_full_snapshot,
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

    snapshot_data_by_window_id = defaultdict(list)

    # Handle backward compatibility to the days of uncompressed and unchunked snapshots
    if "chunk_id" not in all_recording_events[0].snapshot_data:
        paginated_list = paginate_list(all_recording_events, limit, offset)
        for event in paginated_list.paginated_list:
            snapshot_data_by_window_id[event.window_id].append(event.snapshot_data)
        return DecompressedRecordingData(
            has_next=paginated_list.has_next, snapshot_data_by_window_id=snapshot_data_by_window_id
        )

    # Split decompressed recording events into their chunks
    chunks_collector: DefaultDict[str, List[SnapshotDataTaggedWithWindowId]] = defaultdict(list)
    for event in all_recording_events:
        chunks_collector[event.snapshot_data["chunk_id"]].append(event)

    # Paginate the list of chunks
    paginated_chunk_list = paginate_list(list(chunks_collector.values()), limit, offset)

    has_next = paginated_chunk_list.has_next
    chunk_list: List[List[SnapshotDataTaggedWithWindowId]] = paginated_chunk_list.paginated_list

    # Decompress the chunks and split the resulting events by window_id
    for chunks in chunk_list:
        if len(chunks) != chunks[0].snapshot_data["chunk_count"]:
            capture_message(
                "Did not find all session recording chunks! Team: {}, Session: {}, Chunk-id: {}. Found {} of {} expected chunks".format(
                    team_id,
                    session_recording_id,
                    chunks[0].snapshot_data["chunk_id"],
                    len(chunks),
                    chunks[0].snapshot_data["chunk_count"],
                )
            )
            continue

        b64_compressed_data = "".join(
            chunk.snapshot_data["data"] for chunk in sorted(chunks, key=lambda c: c.snapshot_data["chunk_index"])
        )
        decompressed_data = json.loads(decompress(b64_compressed_data))

        # Decompressed data can be large, and in metadata calculations, we only care if the event is "active"
        # This pares down the data returned, so we're not passing around a massive object
        if return_only_activity_data:
            events_with_only_activity_data = [
                {"timestamp": recording_event.get("timestamp"), "is_active": is_active_event(recording_event)}
                for recording_event in decompressed_data
            ]
            snapshot_data_by_window_id[chunks[0].window_id].extend(events_with_only_activity_data)

        else:
            snapshot_data_by_window_id[chunks[0].window_id].extend(decompressed_data)
    return DecompressedRecordingData(has_next=has_next, snapshot_data_by_window_id=snapshot_data_by_window_id)


def is_active_event(event: SnapshotData) -> bool:
    """
    Determines which rr-web events are "active" - meaning user generated
    """
    active_rr_web_sources = [
        1,  # "MouseMove"
        2,  # "MouseInteraction"
        3,  # "Scroll"
        4,  # "ViewportResize"
        5,  # "Input"
        6,  # "TouchMove"
        7,  # "MediaInteraction"
        12,  # "Drag"
    ]
    return event.get("type") == 3 and event.get("data", {}).get("source") in active_rr_web_sources


ACTIVITY_THRESHOLD_SECONDS = 60


def get_active_segments_from_event_list(
    event_list: List[EventActivityData], window_id: WindowId, activity_threshold_seconds=ACTIVITY_THRESHOLD_SECONDS
) -> List[RecordingSegment]:
    """
    Processes a list of events for a specific window_id to determine
    the segments of the recording where the user is "active". And active segment ends
    when there isn't another active event for activity_threshold_seconds seconds
    """
    active_event_timestamps = [event.timestamp for event in event_list if event.is_active]

    active_recording_segments: List[RecordingSegment] = []
    current_active_segment: Optional[RecordingSegment] = None
    for current_timestamp in active_event_timestamps:
        # If the time since the last active event is less than the threshold, continue the existing segment
        if current_active_segment and (current_timestamp - current_active_segment.end_time) <= timedelta(
            seconds=activity_threshold_seconds
        ):
            current_active_segment.end_time = current_timestamp

        # Otherwise, start a new segment
        else:
            if current_active_segment:
                active_recording_segments.append(current_active_segment)
            current_active_segment = RecordingSegment(
                start_time=current_timestamp, end_time=current_timestamp, window_id=window_id, is_active=True,
            )

    # Add the active last segment if it hasn't already been added
    if current_active_segment and (
        len(active_recording_segments) == 0 or active_recording_segments[-1] != current_active_segment
    ):
        active_recording_segments.append(current_active_segment)

    return active_recording_segments


def generate_inactive_segments_for_range(
    range_start_time: datetime,
    range_end_time: datetime,
    last_active_window_id: WindowId,
    start_and_end_times_by_window_id: Dict[WindowId, Dict],
    is_first_segment: bool = False,
    is_last_segment: bool = False,
) -> List[RecordingSegment]:
    """
    Given the start and end times of a known period of inactivity,
    this function will try create recording segments to fill the gap based on the
    start and end times of the given window_ids
    """

    window_ids_by_start_time = sorted(
        start_and_end_times_by_window_id, key=lambda x: start_and_end_times_by_window_id[x]["start_time"]
    )

    # Order of window_ids to use for generating inactive segments. Start with the window_id of the
    # last active segment, then try the other window_ids in order of start_time
    window_id_priority_list: List[WindowId] = [last_active_window_id] + window_ids_by_start_time

    inactive_segments: List[RecordingSegment] = []
    current_time = range_start_time

    for window_id in window_id_priority_list:
        window_start_time = start_and_end_times_by_window_id[window_id]["start_time"]
        window_end_time = start_and_end_times_by_window_id[window_id]["end_time"]
        if window_end_time > current_time and current_time < range_end_time:
            # Add/subtract a millisecond to make sure the segments don't exactly overlap
            segment_start_time = max(window_start_time, current_time)
            segment_end_time = min(window_end_time, range_end_time)
            inactive_segments.append(
                RecordingSegment(
                    start_time=segment_start_time, end_time=segment_end_time, window_id=window_id, is_active=False,
                )
            )
            current_time = min(segment_end_time, window_end_time)

    # Ensure segments don't exactly overlap. This makes the corresponding player logic simpler
    for index, segment in enumerate(inactive_segments):
        if (index == 0 and segment.start_time == range_start_time and not is_first_segment) or (
            index > 0 and segment.start_time == inactive_segments[index - 1].end_time
        ):
            segment.start_time = segment.start_time + timedelta(milliseconds=1)

        if index == len(inactive_segments) - 1 and segment.end_time == range_end_time and not is_last_segment:
            segment.end_time = segment.end_time - timedelta(milliseconds=1)

    return inactive_segments


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
