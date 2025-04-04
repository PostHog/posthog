import csv
from datetime import datetime
import json
from typing import Any
from urllib.parse import urlparse


def load_sesssion_recording_events_from_csv(file_path: str) -> tuple[list[str], list[list[str | None]]]:
    headers = []
    rows = []
    with open(file_path) as f:
        reader = csv.reader(f)
        headers = next(reader)
        rows = [list(row) for row in reader]
    # Replace the headers with custom one to replicate DB response for recordings
    override_headers = [
        "event",
        "timestamp",
        "elements_chain_href",
        "elements_chain_texts",
        "elements_chain_elements",
        "$window_id",
        "$current_url",
        "$event_type",
    ]
    if len(headers) != len(override_headers):
        raise ValueError(
            f"Headers length mismatch when loading session recording events from CSV: {len(headers)} != {len(override_headers)}"
        )
    # Ensure chronolical order of the events
    timestamp_index = get_column_index(override_headers, "timestamp")
    if timestamp_index is not None:
        for i, row in enumerate(rows):
            rows[i][timestamp_index] = prepare_datetime(row[timestamp_index])
        rows.sort(key=lambda x: x[timestamp_index])
    return override_headers, rows


def load_session_metadata_from_json(file_path: str) -> dict[str, Any]:
    with open(file_path) as f:
        raw_session_metadata = json.load(f)
    raw_session_metadata["start_time"] = prepare_datetime(raw_session_metadata.get("start_time"))
    raw_session_metadata["end_time"] = prepare_datetime(raw_session_metadata.get("end_time"))
    return raw_session_metadata


def get_column_index(columns: list[str], column_name: str) -> int | None:
    for i, c in enumerate(columns):
        if c == column_name:
            return i
    return None


def prepare_datetime(raw_time: datetime | str | None) -> datetime | None:
    if not raw_time:
        return None
    if isinstance(raw_time, str):
        return datetime.fromisoformat(raw_time)
    return raw_time


def shorten_url(url: str, max_length: int = 256) -> str:
    """
    Shorten long URLs to a more readable length, trying to keep the context.
    """
    if len(url) <= max_length:
        return url
    parsed = urlparse(url)
    # If it's just a long path - keep it and return as is
    if not parsed.query and not parsed.fragment:
        return url
    base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    # Calculate how many chars we can keep from query
    # Subtract "[...]" length that we'll add between parts
    remaining_length = max_length - len(base_url) - 5
    # If query is the longer part
    if parsed.query and len(parsed.query) > len(parsed.fragment):
        query_start = parsed.query[: remaining_length // 2]
        query_end = parsed.query[-remaining_length // 2 :]
        return f"{base_url}?{query_start}[...]{query_end}"
    # If fragment is the longer part
    if parsed.fragment and len(parsed.fragment) > len(parsed.query):
        fragment_start = parsed.fragment[: remaining_length // 2]
        fragment_end = parsed.fragment[-remaining_length // 2 :]
        return f"{base_url}#{fragment_start}[...]{fragment_end}"
    # If unclear - return the base URL
    return f"{base_url}"
