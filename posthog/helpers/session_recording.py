import base64
import gzip
import json
from collections import defaultdict
from typing import DefaultDict, Dict, Generator, List, Optional

from sentry_sdk.api import capture_exception, capture_message

from posthog.models import utils
from posthog.models.session_recording_event import SessionRecordingEvent
from posthog.utils import PaginatedList, paginate_list

Event = Dict
SnapshotData = Dict


FULL_SNAPSHOT = 2


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


def decompress_chunked_snapshot_data(
    team_id: int, session_recording_id: str, snapshot_list: List[SnapshotData]
) -> Generator[SnapshotData, None, None]:
    chunks_collector = defaultdict(list)
    for snapshot_data in snapshot_list:
        if "chunk_id" not in snapshot_data:
            yield snapshot_data
        else:
            chunks_collector[snapshot_data["chunk_id"]].append(snapshot_data)

    for chunks in chunks_collector.values():
        if len(chunks) != chunks[0]["chunk_count"]:
            capture_message(
                "Did not find all session recording chunks! Team: {}, Session: {}".format(team_id, session_recording_id)
            )
            continue

        b64_compressed_data = "".join(chunk["data"] for chunk in sorted(chunks, key=lambda c: c["chunk_index"]))
        decompressed_data = json.loads(decompress(b64_compressed_data))

        yield from decompressed_data


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


def paginate_chunk_decompression_by_window_id(
    team_id: int,
    session_recording_id: str,
    all_recording_events: List[SessionRecordingEvent],
    limit: Optional[int] = None,
    offset: int = 0,
) -> PaginatedList:
    if len(all_recording_events) == 0:
        return PaginatedList(has_next=False, paginated_list=[])

    snapshot_data_by_window_id: defaultdict(list) = defaultdict(list)

    # Simple case of unchunked and therefore uncompressed snapshots
    if "chunk_id" not in all_recording_events[0].snapshot_data:
        paginated_list = paginate_list(all_recording_events, limit, offset)
        for event in paginated_list.paginated_list:
            snapshot_data_by_window_id[event.window_id].append(event.snapshot_data)
        return {
            "has_next": paginated_list.has_next,
            "snapshot_data_by_window_id": snapshot_data_by_window_id,
        }

    chunks_collector: DefaultDict[str, List[SnapshotData]] = defaultdict(list)

    for event in all_recording_events:
        chunks_collector[event.snapshot_data["chunk_id"]].append(event)

    paginated_chunk_list = paginate_list(list(chunks_collector.values()), limit, offset)

    for chunks in paginated_chunk_list.paginated_list:
        if len(chunks) != chunks[0].snapshot_data["chunk_count"]:
            capture_message(
                "Did not find all session recording chunks! Team: {}, Session: {}, Chunk-id: {}. Found {} of {} chunks".format(
                    team_id, session_recording_id, chunks[0]["chunk_id"], len(chunks), chunks[0]["chunk_count"],
                )
            )
            continue

        b64_compressed_data = "".join(
            chunk.snapshot_data["data"] for chunk in sorted(chunks, key=lambda c: c.snapshot_data["chunk_index"])
        )
        decompressed_data = json.loads(decompress(b64_compressed_data))

        snapshot_data_by_window_id[chunks[0].window_id].extend(decompressed_data)
    return {
        "has_next": paginated_chunk_list.has_next,
        "snapshot_data_by_window_id": snapshot_data_by_window_id,
    }


def is_active_event(event: SnapshotData) -> bool:
    # Determines which rr-web events are "active" - meaning user generated
    # Event type 3 means incremental_update (not a full snapshot, metadata etc)
    # And the following are the defined source types:
    # Mutation = 0
    # MouseMove = 1
    # MouseInteraction = 2
    # Scroll = 3
    # ViewportResize = 4
    # Input = 5
    # TouchMove = 6
    # MediaInteraction = 7
    # StyleSheetRule = 8
    # CanvasMutation = 9
    # Font = 10
    # Log = 11
    # Drag = 12
    # StyleDeclaration = 13
    return event.get("type") == 3 and event.get("data", {}).get("source") in [1, 2, 3, 4, 5, 6, 7, 12]
