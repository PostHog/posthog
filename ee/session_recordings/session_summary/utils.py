import csv
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse
from django.template import Engine, Context

from posthog.session_recordings.queries.session_replay_events import DEFAULT_EVENT_FIELDS


def load_session_recording_events_from_csv(
    file_path: str, extra_fields: list[str]
) -> tuple[list[str], list[tuple[str | datetime | list[str] | None, ...]]]:
    rows = []
    headers_indexes: dict[str, dict[str, Any]] = {
        "event": {"regex": r"event", "indexes": [], "multi_column": False},
        "timestamp": {"regex": r"timestamp", "indexes": [], "multi_column": False},
        "elements_chain_href": {"regex": r"elements_chain_href", "indexes": [], "multi_column": False},
        "elements_chain_texts": {"regex": r"elements_chain_texts\.\d+", "indexes": [], "multi_column": True},
        "elements_chain_elements": {"regex": r"elements_chain_elements\.\d+", "indexes": [], "multi_column": True},
        "$window_id": {"regex": r"properties\.\$window_id", "indexes": [], "multi_column": False},
        "$current_url": {"regex": r"properties\.\$current_url", "indexes": [], "multi_column": False},
        "$event_type": {"regex": r"properties\.\$event_type", "indexes": [], "multi_column": False},
        "elements_chain_ids": {"regex": r"elements_chain_ids\.\d+", "indexes": [], "multi_column": True},
        "elements_chain": {"regex": r"elements_chain", "indexes": [], "multi_column": False},
    }
    allowed_headers = [x.replace("properties.", "") for x in DEFAULT_EVENT_FIELDS] + extra_fields
    if list(headers_indexes.keys()) != allowed_headers:
        raise ValueError(
            f"Headers {headers_indexes.keys()} do not match expected headers {DEFAULT_EVENT_FIELDS + extra_fields}"
        )
    with open(file_path) as f:
        reader = csv.reader(f)
        raw_headers = next(reader)
        for i, raw_header in enumerate(raw_headers):
            for header_metadata in headers_indexes.values():
                regex_to_match = header_metadata.get("regex")
                if not regex_to_match:
                    raise ValueError(f"Header {raw_header} has no regex to match")
                if re.match(regex_to_match, raw_header):
                    header_metadata["indexes"].append(i)
                    break
        # Ensure all headers have indexes
        for header_metadata in headers_indexes.values():
            if not header_metadata["indexes"]:
                raise ValueError(f"Header {header_metadata['regex']} not found in the CSV")
        # Read rows
        timestamp_index = get_column_index(list(headers_indexes.keys()), "timestamp")
        for raw_row in reader:
            row: list[str | datetime | list[str] | None] = []
            for header_index, header_metadata in headers_indexes.items():
                if len(header_metadata["indexes"]) == 1:
                    raw_row_value = raw_row[header_metadata["indexes"][0]]
                    # Ensure to keep the format for multi-column fields
                    if raw_row_value:
                        if header_metadata["multi_column"]:
                            row.append([raw_row_value])
                        else:
                            row.append(raw_row_value)
                    else:
                        if header_metadata["multi_column"]:
                            row.append([])
                        elif header_index in ("$window_id", "$current_url"):
                            row.append(None)
                        else:
                            row.append("")
                # Ensure to combine all values for multi-column fields (like chain texts) into a single list
                else:
                    # Store only non-empty values
                    all_values = [raw_row_value for i in header_metadata["indexes"] if (raw_row_value := raw_row[i])]
                    row.append(all_values)
            timestamp_str = raw_row[timestamp_index]
            row = [*row[:timestamp_index], prepare_datetime(timestamp_str), *row[timestamp_index + 1 :]]
            rows.append(tuple(row))
        # Ensure chronological order of the events
        rows.sort(key=lambda x: x[timestamp_index])  # type: ignore
    session_events_columns, session_events = list(headers_indexes.keys()), rows
    if not session_events_columns or not session_events:
        raise ValueError(f"No events found when loading session recording events from {file_path}")
    return session_events_columns, session_events


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


def serialize_to_sse_event(event_label: str, event_data: str) -> str:
    """
    Serialize data into a Server-Sent Events (SSE) message format.
    Args:
        event_label: The type of event (e.g. "session-summary-stream" or "error")
        event_data: The data to be sent in the event (most likely JSON-serialized)
    Returns:
        A string formatted according to the SSE specification
    """
    # Escape new lines in event label
    event_label = event_label.replace("\n", "\\n")
    # Check (cheap) if event data is JSON-serialized, no need to escape
    if (event_data.startswith("{") and event_data.endswith("}")) or (
        event_data.startswith("[") and event_data.endswith("]")
    ):
        return f"event: {event_label}\ndata: {event_data}\n\n"
    # Otherwise, escape newlines also
    event_data = event_data.replace("\n", "\\n")
    return f"event: {event_label}\ndata: {event_data}\n\n"
