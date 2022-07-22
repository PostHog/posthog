import base64
import dataclasses
import gzip
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import DefaultDict, Dict, Generator, List, Optional, Tuple, cast

from sentry_sdk.api import capture_exception, capture_message

from posthog.models import utils

FULL_SNAPSHOT = 2

Event = Dict
SnapshotData = Dict
WindowId = Optional[str]


@dataclasses.dataclass
class RecordingEventForObjectStorage:
    unix_timestamp: int
    recording_event_id: str
    session_id: str
    distinct_id: str
    chunk_count: int
    chunk_index: int
    recording_event_data_chunk: str
    recording_event_source: Optional[int] = None
    recording_event_type: Optional[int] = None
    window_id: Optional[str] = None


@dataclasses.dataclass
class EventActivityData:
    timestamp: datetime
    is_active: bool


@dataclasses.dataclass
class RecordingEventSummary:
    timestamp: datetime
    window_id: str
    type: int
    source: Optional[int]


@dataclasses.dataclass
class RecordingSegment:
    start_time: datetime
    end_time: datetime
    window_id: WindowId
    is_active: bool


@dataclasses.dataclass
class SnapshotDataTaggedWithWindowId:
    window_id: WindowId
    snapshot_data: SnapshotData


@dataclasses.dataclass
class DecompressedRecordingData:
    has_next: bool
    snapshot_data_by_window_id: Dict[WindowId, List[SnapshotData]]


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


def get_event_summaries_from_compressed_snapshot_data(
    team_id: int, session_recording_id: str, all_recording_events: List[SnapshotDataTaggedWithWindowId],
) -> List[RecordingEventSummary]:
    """
    This function takes in chunked + compresses snapshot data and returns
    a list of event summaries that can be used for metadata calculation.

    It tries to do this conversion in a way that never holds an entire decompressed recording
    to decrease the memory usage.
    """

    if len(all_recording_events) == 0:
        return []

    # Split decompressed recording events into their chunks
    chunks_collector: DefaultDict[str, List[SnapshotDataTaggedWithWindowId]] = defaultdict(list)
    for event in all_recording_events:
        chunks_collector[event.snapshot_data["chunk_id"]].append(event)

    chunk_list: List[List[SnapshotDataTaggedWithWindowId]] = list(chunks_collector.values())

    event_summaries: List[RecordingEventSummary] = []

    # Decompress the chunks and split the resulting events by window_id
    for chunk in chunk_list:
        window_id = chunk[0].window_id
        if len(chunk) != chunk[0].snapshot_data["chunk_count"]:
            capture_message(
                "Did not find all session recording chunks! Team: {}, Session: {}, Chunk-id: {}. Found {} of {} expected chunks".format(
                    team_id,
                    session_recording_id,
                    chunk[0].snapshot_data["chunk_id"],
                    len(chunk),
                    chunk[0].snapshot_data["chunk_count"],
                )
            )
            continue

        b64_compressed_data = "".join(
            chunk.snapshot_data["data"] for chunk in sorted(chunk, key=lambda c: c.snapshot_data["chunk_index"])
        )
        decompressed_data = json.loads(decompress(b64_compressed_data))
        event_summaries.extend(
            [
                RecordingEventSummary(
                    timestamp=datetime.fromtimestamp(recording_event.get("timestamp", 0) / 1000, timezone.utc),
                    window_id=window_id,
                    type=recording_event.get("type"),
                    source=recording_event.get("data", {}).get("source"),
                )
                for recording_event in decompressed_data
            ]
        )
    return event_summaries


def decompress_chunked_snapshot_data(
    team_id: int,
    session_recording_id: str,
    all_recording_events: List[SnapshotDataTaggedWithWindowId],
    limit: Optional[int] = None,
    offset: int = 0,
) -> DecompressedRecordingData:
    """
    Before data is stored in clickhouse, it is compressed and then chunked. This function
    gets back to the original data by unchunking the events and then decompressing the data.

    If limit + offset is provided, then it will paginate the decompression by chunks (not by events, because
    you can't decompress an incomplete chunk).

    Depending on the size of the recording, this function can return a lot of data. To decrease the
    memory used, you should use the pagination parameters.
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

        snapshot_data_by_window_id[chunks[0].window_id].extend(decompressed_data)
    return DecompressedRecordingData(has_next=has_next, snapshot_data_by_window_id=snapshot_data_by_window_id)


def is_active_event(event: RecordingEventSummary) -> bool:
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
    return event.type == 3 and event.source in active_rr_web_sources


ACTIVITY_THRESHOLD_SECONDS = 60


def get_active_segments_from_event_list(
    event_list: List[RecordingEventSummary], window_id: WindowId, activity_threshold_seconds=ACTIVITY_THRESHOLD_SECONDS
) -> List[RecordingSegment]:
    """
    Processes a list of events for a specific window_id to determine
    the segments of the recording where the user is "active". And active segment ends
    when there isn't another active event for activity_threshold_seconds seconds
    """
    active_event_timestamps = [event.timestamp for event in event_list if is_active_event(event)]

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


def get_session_recording_events_for_object_storage(
    events: List[Event], chunk_size=512 * 1024
) -> List[RecordingEventForObjectStorage]:
    recording_events_for_object_storage = []
    for event in events:
        if is_unchunked_snapshot(event):
            # TODO: Handle payloads that aren't what we expect
            distinct_id = event["properties"]["distinct_id"]
            session_id = event["properties"]["$session_id"]
            window_id = event["properties"].get("$window_id")
            recording_event_type = event["properties"]["$snapshot_data"].get("type")
            unix_timestamp = event["properties"]["$snapshot_data"]["timestamp"]
            recording_event_source = event["properties"]["$snapshot_data"].get("data", {}).get("source")
            # We need to add the window_id to the $snapshot_data because the $snapshot_data is the only raw data
            # sent to the client for playback, and the window_id is needed for playback
            event["properties"]["$snapshot_data"]["$window_id"] = window_id
            recording_event_string = json.dumps(event["properties"]["$snapshot_data"])
            chunked_recording_event_string = chunk_string(recording_event_string, chunk_size)
            recording_event_id = str(utils.UUIDT())
            chunk_count = len(chunked_recording_event_string)
            for chunk_index, chunk in enumerate(chunked_recording_event_string):
                recording_events_for_object_storage.append(
                    RecordingEventForObjectStorage(
                        recording_event_id=recording_event_id,
                        distinct_id=distinct_id,
                        session_id=session_id,
                        window_id=window_id,
                        recording_event_type=recording_event_type,
                        recording_event_source=recording_event_source,
                        recording_event_data_chunk=chunk,
                        chunk_count=chunk_count,
                        chunk_index=chunk_index,
                        unix_timestamp=unix_timestamp,
                    )
                )
    return recording_events_for_object_storage


def get_metadata_from_event_summaries(
    event_summaries: List[RecordingEventSummary],
) -> Tuple[List[RecordingSegment], Dict[WindowId, Dict]]:
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

    (4) To complete the recording, we fill in the gaps between active segments with "inactive segments". In
    determining which window should be used for the inactive segment, we try to minimize the switching of windows.
    """

    event_summaries_by_window_id: DefaultDict[WindowId, List[RecordingEventSummary]] = defaultdict(list)
    for event_summary in event_summaries:
        event_summaries_by_window_id[event_summary.window_id].append(event_summary)

    start_and_end_times_by_window_id = {}

    # Get the active segments for each window_id
    all_active_segments: List[RecordingSegment] = []
    for window_id, event_list in event_summaries_by_window_id.items():
        # Not sure why, but events are sometimes slightly out of order
        event_list.sort(key=lambda x: x.timestamp)

        active_segments_for_window_id = get_active_segments_from_event_list(event_list, window_id)

        all_active_segments.extend(active_segments_for_window_id)

        start_and_end_times_by_window_id[window_id] = {
            "start_time": event_list[0].timestamp,
            "end_time": event_list[-1].timestamp,
        }

    # Sort the active segments by start time. This will interleave active segments
    # from different windows
    all_active_segments.sort(key=lambda segment: segment.start_time)

    # These start and end times are used to make sure the segments span the entire recording
    first_start_time = min([cast(datetime, x["start_time"]) for x in start_and_end_times_by_window_id.values()])
    last_end_time = max([cast(datetime, x["end_time"]) for x in start_and_end_times_by_window_id.values()])

    # Now, we fill in the gaps between the active segments with inactive segments
    all_segments = []
    current_timestamp = first_start_time
    current_window_id: WindowId = sorted(
        start_and_end_times_by_window_id, key=lambda x: start_and_end_times_by_window_id[x]["start_time"]
    )[0]

    for index, segment in enumerate(all_active_segments):
        # It's possible that segments overlap and we don't need to fill a gap
        if segment.start_time > current_timestamp:
            all_segments.extend(
                generate_inactive_segments_for_range(
                    current_timestamp,
                    segment.start_time,
                    current_window_id,
                    start_and_end_times_by_window_id,
                    is_first_segment=index == 0,
                )
            )
        all_segments.append(segment)
        current_window_id = segment.window_id
        current_timestamp = max(segment.end_time, current_timestamp)

    # If the last segment ends before the recording ends, we need to fill in the gap
    if current_timestamp < last_end_time:
        all_segments.extend(
            generate_inactive_segments_for_range(
                current_timestamp,
                last_end_time,
                current_window_id,
                start_and_end_times_by_window_id,
                is_last_segment=True,
                is_first_segment=current_timestamp == first_start_time,
            )
        )

    return all_segments, start_and_end_times_by_window_id
