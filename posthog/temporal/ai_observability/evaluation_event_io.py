from typing import Any


def extract_event_io(event_type: str, properties: dict[str, Any]) -> tuple[Any, Any]:
    """Extract raw input and output values from event properties.

    Returns (input_raw, output_raw) for use in Hog eval globals and preview display.

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
    return input_raw, output_raw


def extract_event_tools(properties: dict[str, Any]) -> Any:
    """Extract the tool catalog (`$ai_tools`) captured on the event, regardless
    of event type.

    `$ai_generation` is the canonical carrier today, but custom span/trace
    events (e.g. an agent loop's `run_summary`) may also forward the catalog,
    and the judge prompt benefits from it for any event shape. Presence of
    `$ai_tools` drives whether the Tools section renders.
    """
    return properties.get("$ai_tools")
