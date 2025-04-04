import csv
import json
from typing import Any

from ee.session_recordings.ai.prompt_data import get_column_index, prepare_datetime


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
