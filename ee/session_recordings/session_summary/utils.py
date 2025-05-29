import csv
from datetime import datetime
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from django.template import Engine, Context


def load_session_recording_events_from_csv(file_path: str) -> tuple[list[str], list[list[str | datetime]]]:
    headers = []
    rows: list[list[str | datetime]] = []
    with open(file_path) as f:
        reader = csv.reader(f)
        headers = next(reader)
        # Ensure chronological order of the events
        timestamp_index = get_column_index(headers, "timestamp")
        if not timestamp_index:
            raise ValueError("Timestamp column not found in the CSV")
        for raw_row in reader:
            row: list[str | datetime] = []
            timestamp_str = raw_row[timestamp_index]
            timestamp = prepare_datetime(timestamp_str)
            row = [*raw_row[:timestamp_index], timestamp, *raw_row[timestamp_index + 1 :]]
            rows.append(row)
        rows.sort(key=lambda x: x[timestamp_index])
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


def load_session_metadata_from_json(file_path: str) -> dict[str, Any]:
    with open(file_path) as f:
        raw_session_metadata = json.load(f)
    raw_session_metadata["start_time"] = prepare_datetime(raw_session_metadata.get("start_time"))
    raw_session_metadata["end_time"] = prepare_datetime(raw_session_metadata.get("end_time"))
    return raw_session_metadata


def get_column_index(columns: list[str], column_name: str) -> int:
    for i, c in enumerate(columns):
        if c == column_name:
            return i
    else:
        raise ValueError(f"Column {column_name} not found in the columns: {columns}")


def prepare_datetime(raw_time: datetime | str) -> datetime:
    # Assuming that timestamps are always present and follow ISO format
    if isinstance(raw_time, str):
        return datetime.fromisoformat(raw_time)
    return raw_time


def _split_url_part(part: str, divider: int) -> tuple[str, str]:
    part_start = part[:divider]
    part_end = part[-divider:]
    return part_start, part_end


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
    # Subtract "[...]" that we'll add between parts
    remaining_length = max_length - len(base_url) - 5
    # If query is the longer part
    if parsed.query and len(parsed.query) > len(parsed.fragment):
        if len(parsed.fragment) > 0:
            remaining_length = remaining_length - len(parsed.fragment) - 2
            query_start, query_end = _split_url_part(parsed.query, remaining_length // 2)
            return f"{base_url}?{query_start}[...]{query_end}#{parsed.fragment}"
        else:
            remaining_length = remaining_length - 1
            query_start, query_end = _split_url_part(parsed.query, remaining_length // 2)
            return f"{base_url}?{query_start}[...]{query_end}"
    # If fragment is the longer part
    if parsed.fragment and len(parsed.fragment) > len(parsed.query):
        if len(parsed.query) > 0:
            remaining_length = remaining_length - len(parsed.query) - 2
            fragment_start, fragment_end = _split_url_part(parsed.fragment, remaining_length // 2)
            return f"{base_url}?{parsed.query}#{fragment_start}[...]{fragment_end}"
        else:
            remaining_length = remaining_length - 1
            fragment_start, fragment_end = _split_url_part(parsed.fragment, remaining_length // 2)
            return f"{base_url}#{fragment_start}[...]{fragment_end}"
    # If unclear - return the base URL
    return f"{base_url}"


def load_custom_template(template_dir: Path, template_name: str, context: dict | None = None) -> str:
    """
    Load and render a template from the session summary templates directory.
    A custom function to load templates from non-standard location.
    """
    template_path = template_dir / template_name
    if not template_path.exists():
        raise FileNotFoundError(f"Template {template_name} not found in {template_dir}")
    with open(template_path) as f:
        template_string = f.read()
    # Create a new Engine instance with our template directory
    engine = Engine(
        debug=True,
        libraries={},
    )
    # Create template from string
    template = engine.from_string(template_string)
    # Render template with context
    return template.render(Context(context or {}))
