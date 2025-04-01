import csv
import json


def load_sesssion_recording_events_from_csv(file_path: str) -> tuple[list[str], list[tuple[str | None, ...]]]:
    headers = []
    rows = []
    with open(file_path) as f:
        reader = csv.reader(f)
        headers = next(reader)
        rows = [tuple(row) for row in reader]
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
    return override_headers, rows


def load_session_metadata_from_json(file_path: str) -> dict:
    with open(file_path) as f:
        return json.load(f)
