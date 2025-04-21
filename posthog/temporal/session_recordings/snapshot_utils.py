import gzip
import json
from typing import Any, cast

from posthog.storage import object_storage
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.session_recording_v2_service import list_blocks
from posthog.storage.session_recording_v2_object_storage import client as v2_client
from posthog.temporal.session_recordings.session_comparer import transform_v2_snapshot, transform_v1_snapshots


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


def fetch_v1_snapshots(recording: SessionRecording) -> list[dict[str, Any]]:
    """Fetch and transform v1 snapshots for a recording."""
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
    return v1_snapshots


def fetch_v2_snapshots(recording: SessionRecording) -> list[dict[str, Any]]:
    """Fetch and transform v2 snapshots for a recording."""
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
            except Exception:
                # Exception handling should be done by the caller
                raise
    return v2_snapshots
