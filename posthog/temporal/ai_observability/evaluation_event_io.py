from datetime import UTC, datetime
from typing import Any

from temporalio.exceptions import ApplicationError

from posthog.dataclasses import frozen

from products.ai_observability.backend.ai_event_lookup import fetch_generation_event


def as_utc_datetime(value: str | datetime) -> datetime:
    """Read a ClickHouse event timestamp, which reaches us as a naive datetime on a direct call
    and as an ISO string once Temporal has serialized it through a payload."""
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@frozen
class EventIO:
    input_raw: Any
    output_raw: Any


def extract_event_io(event_type: str, properties: dict[str, Any]) -> EventIO:
    """Extract raw input and output values from event properties.

    Returns an `EventIO` for use in Hog eval globals and preview display.

    Invariant: `properties` must already contain the heavy `$ai_*` keys when present
    on the source event. Heavy columns live only on the dedicated `ai_events` table —
    they are not stored in `events.properties` — so callers must source the event from
    a path that re-populates them. Today that's `EvaluationRunViewSet.create`, which
    reads from `ai_events` and re-merges heavy columns via `merge_heavy_properties`
    before handing `event_data` to this workflow. Adding a new caller? Use the same
    pattern, or feed it `event_data` produced by an already-`ai_events`-backed reader.

    If `properties` arrives without the heavy keys (e.g. sourced from a stripped
    `events` row), `extract_event_io` returns empty `input_raw` / `output_raw` and the
    LLM judge / Hog eval would silently grade an empty conversation — hence the invariant.
    """
    if event_type == "$ai_generation":
        input_raw = properties.get("$ai_input") or properties.get("$ai_input_state", "")
        output_raw = (
            properties.get("$ai_output_choices")
            or properties.get("$ai_output")
            or properties.get("$ai_output_state", "")
        )
    else:
        input_raw = properties.get("$ai_input_state", "")
        output_raw = properties.get("$ai_output_state", "")
    return EventIO(input_raw=input_raw, output_raw=output_raw)


def extract_event_tools(properties: dict[str, Any]) -> Any:
    """Extract the tool catalog (`$ai_tools`) captured on the event, regardless
    of event type.

    `$ai_generation` is the canonical carrier today, but custom span/trace
    events (e.g. an agent loop's `run_summary`) may also forward the catalog,
    and the judge prompt benefits from it for any event shape. Presence of
    `$ai_tools` drives whether the Tools section renders.
    """
    return properties.get("$ai_tools")


def hydrate_event_reference(event_data: dict[str, Any]) -> dict[str, Any]:
    """Load the generation when `event_data` carries only a reference to it.

    Capture accepts an AI event up to 8 MiB while a Temporal payload is capped near 2 MiB, so a
    large generation cannot cross the workflow boundary at all. A backfill dispatcher therefore
    ships the uuid, plus the timestamp and trace id that turn the read into a point lookup on the
    ai_events sort key, and every activity that needs the body reads it here.

    Lives in this module rather than next to the activities because both the activities module and
    the LLM judge module call it, and the activities module already imports the judge.
    """
    if "properties" in event_data:
        return event_data
    raw_timestamp = event_data.get("timestamp")
    event = fetch_generation_event(
        int(event_data["team_id"]),
        str(event_data["uuid"]),
        as_utc_datetime(raw_timestamp) if raw_timestamp else None,
        event_data.get("trace_id"),
    )
    if event is None:
        raise ApplicationError("Generation not found", type="generation_not_found", non_retryable=True)
    return event
