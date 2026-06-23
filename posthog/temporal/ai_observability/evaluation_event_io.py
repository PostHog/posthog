from typing import Any


def extract_event_io(event_type: str, properties: dict[str, Any]) -> tuple[Any, Any]:
    """Extract raw input and output values from event properties.

    Returns (input_raw, output_raw) for use in Hog eval globals and preview display.

    Invariant: `properties` must already contain the heavy `$ai_*` keys when present
    on the source event. Heavy props are stripped from `events.properties` after the
    cutover (see AI events migration brief), so callers must source the event from a
    path that re-populates them — today that's `EvaluationRunViewSet.create`, which
    reads from `ai_events` and re-merges heavy columns via `merge_heavy_properties`
    before handing `event_data` to this workflow. Adding a new caller? Use the same
    pattern, or feed it `event_data` produced by an already-migrated reader.

    Failure mode this invariant guards against: when `is_ai_events_enabled(team)` is
    False (kill switch flipped) AND the team is post-strip, the events-fallback path
    in `EvaluationRunViewSet.create` returns rows whose `properties` JSON has NULL
    heavy keys. `extract_event_io` would then return empty `input_raw` / `output_raw`,
    and the LLM judge / Hog eval would silently grade an empty conversation. The
    invariant exists so any future caller short-circuiting around the migrated
    reader has to confront this case explicitly.
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
