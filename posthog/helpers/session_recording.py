import base64
import gzip
import json
from collections import defaultdict
from typing import Dict, Generator, List

from sentry_sdk.api import capture_message

from posthog.models import utils

Event = Dict
SnapshotData = Dict

FULL_SNAPSHOT = 2


def preprocess_session_recording_events(events: List[Event]) -> List[Event]:
    result = []
    snapshots_by_session = defaultdict(list)
    for event in events:
        if is_snapshot(event):
            session_recording_id = event["properties"]["$session_id"]
            snapshots_by_session[session_recording_id].append(event)
        else:
            result.append(event)

    for session_recording_id, snapshots in snapshots_by_session.items():
        result.extend(list(compress_and_chunk_snapshots(snapshots)))

    return result


def compress_and_chunk_snapshots(events: List[Event], chunk_size=512 * 1024) -> Generator[Event, None, None]:
    data_list = [event["properties"]["$snapshot_data"] for event in events]
    session_id = events[0]["properties"]["$session_id"]
    has_full_snapshot = any(snapshot_data["type"] == FULL_SNAPSHOT for snapshot_data in data_list)

    compressed_data = compress_to_string(json.dumps(data_list))

    id = str(utils.UUIDT())
    chunks = chunk_string(compressed_data, chunk_size)
    for index, chunk in enumerate(chunks):
        yield {
            **events[0],
            "properties": {
                **events[0]["properties"],
                "$session_id": session_id,
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


def is_snapshot(event: Dict) -> bool:
    return event["event"] == "$snapshot"


def compress_to_string(json_string: str) -> str:
    compressed_data = gzip.compress(json_string.encode("utf-16", "surrogatepass"))
    return base64.b64encode(compressed_data).decode("utf-8")


def decompress(base64data: str) -> str:
    compressed_bytes = base64.b64decode(base64data)
    return gzip.decompress(compressed_bytes).decode("utf-16", "surrogatepass")
