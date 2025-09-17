from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from django.template import Context, Engine

import tiktoken

from ee.hogai.session_summaries.constants import MAX_SESSION_IDS_COMBINED_LOGGING_LENGTH


def get_column_index(columns: list[str], column_name: str) -> int:
    for i, c in enumerate(columns):
        if c.replace("$", "") == column_name.replace("$", ""):
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


def generate_full_event_id(session_id: str, event_uuid: str) -> str:
    """Generate a full event ID from a session ID and an event UUID to be able to track events across sessions"""
    if not event_uuid:
        raise ValueError(f"UUID is not present when generating event_id for session_id {session_id}")
    full_event_id = f"{session_id}_{event_uuid}"
    return full_event_id


def unpack_full_event_id(full_event_id: str | None, session_id: str | None = None) -> tuple[str, str]:
    """Unpack a full event ID into a session ID and an event UUID"""
    if not full_event_id:
        message = f"Full event ID is not present when unpacking"
        if session_id:
            message = f"{message} for session_id {session_id}"
        raise ValueError(message)
    try:
        unpacked_session_id, event_uuid = full_event_id.split("_")
    except ValueError as err:
        message = f"Invalid full event ID: {full_event_id}"
        if session_id:
            message = f"{message} for session_id {session_id}"
        raise ValueError(message) from err
    if session_id and unpacked_session_id != session_id:
        raise ValueError(
            f"Session ID mismatch when unpacking full event ID for session_id {session_id}: {full_event_id}"
        )
    return unpacked_session_id, event_uuid


def estimate_tokens_from_strings(strings: list[str], model: str) -> int:
    """Estimate the token count for a list of strings."""
    if not strings:
        return 0
    encoding = tiktoken.encoding_for_model(model)
    total_tokens = 0
    for string in strings:
        if string:
            total_tokens += len(encoding.encode(string))
    return total_tokens


def logging_session_ids(session_ids: list[str]) -> str:
    """Log a list of session ids in a readable format."""
    # Having 150 chars (4 uuids) is enough to identify the sessions and stay readable
    return f"Session IDs: {str(session_ids)[:MAX_SESSION_IDS_COMBINED_LOGGING_LENGTH]}"
