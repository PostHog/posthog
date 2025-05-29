from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from django.template import Engine, Context


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
