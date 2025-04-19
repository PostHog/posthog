import csv
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse
from django.template import Engine, Context


def load_session_recording_events_from_csv(file_path: str) -> tuple[list[str], list[list[str | datetime]]]:
    rows = []
    headers_indexes = {
        "event": {"regex": r"event", "indexes": [], "multi_column": False},
        "timestamp": {"regex": r"timestamp", "indexes": [], "multi_column": False},
        "elements_chain_href": {"regex": r"elements_chain_href", "indexes": [], "multi_column": False},
        "elements_chain_texts": {"regex": r"elements_chain_texts\.\d+", "indexes": [], "multi_column": True},
        "elements_chain_elements": {"regex": r"elements_chain_elements\.\d+", "indexes": [], "multi_column": True},
        "properties.$window_id": {"regex": r"properties\.\$window_id", "indexes": [], "multi_column": False},
        "properties.$current_url": {"regex": r"properties\.\$current_url", "indexes": [], "multi_column": False},
        "properties.$event_type": {"regex": r"properties\.\$event_type", "indexes": [], "multi_column": False},
        "elements_chain_ids": {"regex": r"elements_chain_ids\.\d+", "indexes": [], "multi_column": True},
        "elements_chain": {"regex": r"elements_chain", "indexes": [], "multi_column": False},
    }
    with open(file_path) as f:
        reader = csv.reader(f)
        raw_headers = next(reader)
        for i, raw_header in enumerate(raw_headers):
            for header_metadata in headers_indexes.values():
                if re.match(header_metadata["regex"], raw_header):
                    header_metadata["indexes"].append(i)
                    break
        # Ensure all headers have indexes
        for header_metadata in headers_indexes.values():
            if not header_metadata["indexes"]:
                raise ValueError(f"Header {header_metadata['regex']} not found in the CSV")
        # Read rows
        timestamp_index = get_column_index(list(headers_indexes.keys()), "timestamp")
        for raw_row in reader:
            row = []
            for header_metadata in headers_indexes.values():
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
                        else:
                            row.append("")
                # Ensure to combine all values for multi-column fields (like chain texts) into a single list
                else:
                    # Store only non-empty values
                    all_values = [raw_row_value for i in header_metadata["indexes"] if (raw_row_value := raw_row[i])]
                    row.append(all_values)
            timestamp_str = raw_row[timestamp_index]
            row = [*row[:timestamp_index], prepare_datetime(timestamp_str), *row[timestamp_index + 1 :]]
            rows.append(row)
        # Ensure chronological order of the events
        rows.sort(key=lambda x: x[timestamp_index])
    return list(headers_indexes.keys()), rows


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
