import base64
import dataclasses
import gzip
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, DefaultDict, Dict, Generator, List, Optional

from dateutil.parser import ParserError, parse
from prometheus_client import Histogram
from prometheus_client.utils import INF
from sentry_sdk.api import capture_exception, capture_message

from posthog.models import utils
from posthog.models.session_recording.metadata import (
    DecompressedRecordingData,
    RecordingSegment,
    SessionRecordingEventSummary,
    SnapshotData,
    SnapshotDataTaggedWithWindowId,
    WindowId,
)

FULL_SNAPSHOT = 2


# NOTE: For reference here are some helpful enum mappings from rrweb
# https://github.com/rrweb-io/rrweb/blob/master/packages/rrweb/src/types.ts

# event.type

recordingsChunksLength = Histogram(
    "session_recordings_chunks_length",
    "We chunk session recordings to fit them into kafka, how often do we chunk and by how much?",
    buckets=(0, 1, 2, 5, 7, 10, 15, 20, 50, 100, 500, INF),
)


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


def split_replay_events(events: List[Event]) -> List[Event]:
    replay, other = [], []

    for event in events:
        replay.append(event) if is_unchunked_snapshot(event) else other.append(event)

    return replay, other


def compress_replay_events(events: List[Event]) -> List[Event]:
    return [compress_replay_event(event) for event in events]


def compress_replay_event(event: Event) -> Event:
    """
    Takes a single incoming event and compresses the snapshot data
    """
    snapshot_data = event["properties"]["$snapshot_data"]
    compressed_data = compress_to_string(json.dumps(snapshot_data))
    has_full_snapshot = snapshot_data["type"] == RRWEB_MAP_EVENT_TYPE.FullSnapshot
    events_summary = get_events_summary_from_snapshot_data([snapshot_data])

    event["properties"]["$snapshot_data"] = {
        "data": compressed_data,
        "compression": "gzip-base64",
        "has_full_snapshot": has_full_snapshot,
        "events_summary": events_summary,
    }

    return event


def reduce_replay_events_by_window(events: List[Event], max_size_bytes=512 * 1024) -> List[Event]:
    return _process_windowed_events(events, lambda x: reduce_replay_events(x, max_size_bytes))


def reduce_replay_events(events: List[Event], max_size_bytes=512 * 1024) -> List[Event]:
    """
    Now that we have compressed events, we group them based on the max size to reduce the number of events
    written to Kafka
    """
    if len(events) == 0:
        return []

    session_id = events[0]["properties"]["$session_id"]
    window_id = events[0]["properties"].get("$window_id")

    def new_event() -> Event:
        return {
            **events[0],
            "properties": {
                **events[0]["properties"],
                "$session_id": session_id,
                "$window_id": window_id,
                "$snapshot_data": {
                    "data_items": [],
                    "compression": "gzip-base64",
                    "has_full_snapshot": False,
                    "events_summary": [],
                },
            },
        }

    current_event = None

    for event in events:
        additional_snapshot_data = event["properties"]["$snapshot_data"]

        if not current_event:
            current_event = new_event()
        elif byte_size_dict(current_event) + byte_size_dict(additional_snapshot_data) > max_size_bytes:
            # If adding the new data would put us over the max size, yield the current event and start a new one
            yield current_event
            current_event = new_event()

        # Add the existing data to the base event
        current_event["properties"]["$snapshot_data"]["data_items"].append(additional_snapshot_data["data"])
        current_event["properties"]["$snapshot_data"]["events_summary"].extend(
            additional_snapshot_data["events_summary"]
        )
        current_event["properties"]["$snapshot_data"]["has_full_snapshot"] = (
            current_event["properties"]["$snapshot_data"]["has_full_snapshot"]
            or additional_snapshot_data["has_full_snapshot"]
        )

    yield current_event


def chunk_replay_events_by_window(events: List[Event], max_size_bytes=512 * 1024) -> List[Event]:
    return _process_windowed_events(events, lambda x: chunk_replay_events(x, max_size_bytes))


def chunk_replay_events(events: List[Event], max_size_bytes=512 * 1024) -> Generator[Event, None, None]:
    """
    If any of the events individually sits above the max_size_bytes, we compress and chunk the data into multiple events.
    Eventually this won't be needed as we'll be able to write larger events to Kafka
    """
    for event in events:
        print("size", byte_size_dict(event))
        if byte_size_dict(event) > max_size_bytes:
            data_items = event["properties"]["$snapshot_data"]["data_items"]
            events_summary = event["properties"]["$snapshot_data"]["events_summary"]
            has_full_snapshot = event["properties"]["$snapshot_data"]["has_full_snapshot"]
            data = data_items[0]
            # We assume due to the reduce_replay_events function that there will only ever be one event if it is above the threshold
            if len(data_items) > 1:
                capture_message(
                    f"Expected only one snapshot data item but found {len(data_items)} when compressing over threshold!",
                    level="error",
                    extra={"data_items": data_items},
                )

            id = str(utils.UUIDT())
            chunks = chunk_string(data, max_size_bytes)
            recordingsChunksLength.observe(len(chunks))

            for index, chunk in enumerate(chunks):
                yield {
                    **events[0],
                    "properties": {
                        **events[0]["properties"],
                        # If it is the first chunk we include all events
                        "$snapshot_data": {
                            "chunk_id": id,
                            "chunk_index": index,
                            "chunk_count": len(chunks),
                            "data": chunk,
                            "compression": "gzip-base64",
                            "has_full_snapshot": has_full_snapshot,
                            # We only store this field on the first chunk as it contains all events, not just this chunk
                            "events_summary": events_summary if index == 0 else None,
                        },
                    },
                }
        else:
            yield event


def _process_windowed_events(events: List[Event], fn: Callable[[List[Event], Any], List[Event]]) -> List[Event]:
    """
    Helper method to simplify grouping events by window_id and session_id, processing them with the given function, and then returning the flattened list
    """
    result = []
    snapshots_by_session_and_window_id = defaultdict(list)

    for event in events:
        session_id = event["properties"]["$session_id"]
        window_id = event["properties"].get("$window_id")
        snapshots_by_session_and_window_id[(session_id, window_id)].append(event)

    for _, snapshots in snapshots_by_session_and_window_id.items():
        result.extend(fn(snapshots))

    return result


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

    snapshot_data_by_window_id = defaultdict(list)

    # Handle unchunked snapshots
    if "chunk_id" not in all_recording_events[0]["snapshot_data"]:
        paginated_list = paginate_list(all_recording_events, limit, offset)
        for event in paginated_list.paginated_list:

            if event["snapshot_data"].get("data_items"):
                decompressed_items = [json.loads(decompress(x)) for x in event["snapshot_data"]["data_items"]]

                # New format where the event is a list of raw rrweb events
                snapshot_data_by_window_id[event["window_id"]].extend(
                    event["snapshot_data"]["events_summary"] if return_only_activity_data else decompressed_items
                )
            else:
                # Really old format where the event is just a single raw rrweb event
                snapshot_data_by_window_id[event["window_id"]].append(
                    get_events_summary_from_snapshot_data([event["snapshot_data"]])[0]
                    if return_only_activity_data
                    else event["snapshot_data"]
                )
        return DecompressedRecordingData(
            has_next=paginated_list.has_next, snapshot_data_by_window_id=snapshot_data_by_window_id
        )

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
        was_originally_over_complete = False
        if len(chunks) > chunks[0]["snapshot_data"]["chunk_count"]:
            was_originally_over_complete = True
            deduplicated_chunks = {}
            for chunk in chunks:
                # reduce the chunks into deduplicated chunks by chunk_id taking only the first seen for each chunk_id
                if chunk["snapshot_data"]["chunk_index"] not in deduplicated_chunks:
                    deduplicated_chunks[chunk["snapshot_data"]["chunk_index"]] = chunk

            chunks = list(deduplicated_chunks.values())

        # even after deduplication, we don't know we have the right number of chunks
        if len(chunks) != chunks[0]["snapshot_data"]["chunk_count"]:
            capture_message(
                "Did not find all session recording chunks! Team: {}, Session: {}, Chunk-id: {}. Found {} of {} expected chunks".format(
                    team_id,
                    session_recording_id,
                    chunks[0]["snapshot_data"]["chunk_id"],
                    len(chunks),
                    chunks[0]["snapshot_data"]["chunk_count"],
                ),
                tags={
                    "team_id": team_id,
                },
                extras={
                    "session_recording_id": session_recording_id,
                    "expected_chunk_count": chunks[0]["snapshot_data"]["chunk_count"],
                    "received_chunk_count": len(chunks),
                    "was_originally_over_complete": was_originally_over_complete,
                },
            )
            continue

        b64_compressed_data = "".join(
            chunk["snapshot_data"]["data"] for chunk in sorted(chunks, key=lambda c: c["snapshot_data"]["chunk_index"])
        )
        decompressed_data = json.loads(decompress(b64_compressed_data))

        # Decompressed data can be large, and in metadata calculations, we only care if the event is "active"
        # This pares down the data returned, so we're not passing around a massive object
        if return_only_activity_data:
            events_with_only_activity_data = get_events_summary_from_snapshot_data(decompressed_data)
            snapshot_data_by_window_id[chunks[0]["window_id"]].extend(events_with_only_activity_data)
        else:
            snapshot_data_by_window_id[chunks[0]["window_id"]].extend(decompressed_data)
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


def convert_to_timestamp(source: str) -> int:
    return int(parse(source).timestamp() * 1000)


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

        # noinspection PyBroadException
        try:
            events_summary.append(
                SessionRecordingEventSummary(
                    timestamp=int(event["timestamp"])
                    if isinstance(event["timestamp"], (int, float))
                    else convert_to_timestamp(event["timestamp"]),
                    type=event["type"],
                    data=data,
                )
            )
        except ParserError:
            capture_exception()

    # No guarantees are made about order so, we sort here to be sure
    events_summary.sort(key=lambda x: x["timestamp"])

    return events_summary


def generate_inactive_segments_for_range(
    range_start_time: datetime,
    range_end_time: datetime,
    last_active_window_id: WindowId,
    start_and_end_times_by_window_id: Dict[WindowId, RecordingSegment],
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
                    start_time=segment_start_time, end_time=segment_end_time, window_id=window_id, is_active=False
                )
            )
            current_time = min(segment_end_time, window_end_time)

    # Ensure segments don't exactly overlap. This makes the corresponding player logic simpler
    for index, segment in enumerate(inactive_segments):
        if (index == 0 and segment["start_time"] == range_start_time and not is_first_segment) or (
            index > 0 and segment["start_time"] == inactive_segments[index - 1]["end_time"]
        ):
            segment["start_time"] = segment["start_time"] + timedelta(milliseconds=1)

        if index == len(inactive_segments) - 1 and segment["end_time"] == range_end_time and not is_last_segment:
            segment["end_time"] = segment["end_time"] - timedelta(milliseconds=1)

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


def byte_size_dict(d: Dict) -> int:
    return len(json.dumps(d))
