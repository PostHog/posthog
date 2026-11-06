"""Stage 4: fetch one bounded sample of a team's traces and run every applicable Hog check on it.

The sample is spread over the window by trace id hash rather than taken from the latest traces, and the
most recent day with traffic is held out so stage 6 can re-test each check on traces it was not picked on.
"""

import json
import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from posthog.schema import LLMTrace, LLMTraceEvent

from posthog.hogql import ast

from posthog.dataclasses import frozen
from posthog.hogql_queries.ai.utils import merge_heavy_properties
from posthog.models.team import Team
from posthog.temporal.ai_observability.evaluation_hog import build_hog_event_global, execute_hog_eval_bytecode
from posthog.temporal.ai_observability.run_trace_evaluation import build_trace_hog_globals

from .adapters import AdaptedCheck, compile_check
from .profile import (
    ProfileWindow,
    StructuredOutput,
    TeamProfile,
    normalize_segment_value,
    parse_structured,
    short_string_fields,
)
from .queries import run_ai_events_query, run_query

MAIN_SAMPLE_TRACES = 250
HELD_OUT_SAMPLE_TRACES = 150
# Discovery groups only a slice of the window's traces, sized so the hash order still has room to choose.
DISCOVERY_OVERSAMPLE = 20
# Hydration reads every event of a trace, and a check needs a trace's whole history, so discovery only picks
# traces with at most this many events. Longer ones (a shared or runaway trace id) cost the most to read.
EVENTS_PER_TRACE = 40
MAX_OUTPUT_BYTES = 16384
MAX_INPUT_MESSAGE_BYTES = 8192
# Screening reads at most 3000 characters, so each part of a turn gets a third.
TURN_TEXT_CHARS = 1000

_DISCOVER_SQL = """
SELECT
    toString(properties.$ai_trace_id) AS trace_id,
    uniq(toDate(timestamp)) AS days
FROM events
WHERE event IN ('$ai_generation', '$ai_span', '$ai_embedding')
  AND timestamp >= {start}
  AND timestamp < {end}
  AND notEmpty(toString(properties.$ai_trace_id))
  AND length(toString(properties.$ai_trace_id)) <= 256
  AND cityHash64(toString(properties.$ai_trace_id)) % 1000 < {per_mille}
GROUP BY trace_id
HAVING countIf(event = '$ai_generation') > 0 AND count() <= {max_events}
ORDER BY cityHash64(trace_id)
LIMIT {limit}
"""

# Only the last two messages of each input are read: the last is the user's message for the first call of a turn,
# and the one before it is the assistant reply the user answers. Full histories cost far more than checks need.
# Rows are deduplicated by uuid first, since ingestion can write an event twice, and one row past the cap is kept so
# a trace with more events than the cap shows up as incomplete.
_HYDRATE_SQL = """
SELECT
    trace_id,
    event_uuid,
    event,
    timestamp,
    distinct_id,
    properties,
    last_input,
    user_messages,
    has_tool_results,
    output_choices,
    output,
    output_too_long,
    previous_message
FROM (
    SELECT
        trace_id,
        toString(uuid) AS event_uuid,
        event,
        timestamp,
        distinct_id,
        properties,
        if(startsWith(input, '['), concat('[', left(JSONExtractRaw(input, -1), {max_input}), ']'), left(input, {max_input})) AS last_input,
        if(startsWith(input, '[') AND JSONLength(input) >= 2, left(JSONExtractRaw(input, -2), {max_input}), '') AS previous_message,
        countMatches(input, '"role":[[:space:]]*"user"') AS user_messages,
        match(input, '"role":[[:space:]]*"tool"|"type":[[:space:]]*"(tool_result|function_call_output)"') AS has_tool_results,
        if(length(output_choices) <= {max_output}, output_choices, '') AS output_choices,
        if(length(output) <= {max_output}, output, '') AS output,
        length(ai_events.output_choices) > {max_output} OR length(ai_events.output) > {max_output} AS output_too_long
    FROM posthog.ai_events AS ai_events
    WHERE event IN ('$ai_generation', '$ai_span', '$ai_embedding')
      AND trace_id IN {trace_ids}
      AND timestamp >= {start}
      AND timestamp < {end}
    ORDER BY length(coalesce(ai_events.input, '')) + length(coalesce(ai_events.output_choices, '')) DESC
    LIMIT 1 BY event_uuid
)
ORDER BY trace_id, timestamp DESC
LIMIT {rows_per_trace} BY trace_id
LIMIT {max_rows}
"""


@frozen
class SampledTrace:
    trace: LLMTrace
    held_out: bool
    spans_days: bool
    # Normalized values of the team's segment properties, read off the trace's last generation.
    segments: dict[str, str]
    # Every normalized value any generation sent. A trace evaluation runs when any generation matches its filter.
    segment_values: dict[str, frozenset[str]]
    # The same, as sent, which is what an exact live filter compares against.
    raw_segment_values: dict[str, frozenset[str]]
    raw_segments: dict[str, str]
    final_text: str
    turn_text: str
    user_messages: int
    has_tool_results: bool
    input_tokens: float


@frozen
class TraceSample:
    main: list[SampledTrace]
    held_out: list[SampledTrace]

    @property
    def traces(self) -> list[SampledTrace]:
        return self.main + self.held_out


def held_out_bucket(profile: TeamProfile) -> int | None:
    """The most recent 24-hour bucket with generations, when an older bucket has generations too."""
    buckets = sorted(bucket for bucket, count in profile.generations_by_days_ago.items() if count)
    return buckets[0] if len(buckets) >= 2 else None


@frozen
class DiscoveredTrace:
    trace_id: str
    # Distinct days the trace has generations on.
    days: int


def _discover(team: Team, start: datetime, end: datetime, expected_traces: int, limit: int) -> list[DiscoveredTrace]:
    per_mille = (
        1000
        if expected_traces <= limit * DISCOVERY_OVERSAMPLE
        else math.ceil(1000 * limit * DISCOVERY_OVERSAMPLE / expected_traces)
    )
    rows = run_query(
        team,
        _DISCOVER_SQL,
        {
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
            "per_mille": ast.Constant(value=per_mille),
            "max_events": ast.Constant(value=EVENTS_PER_TRACE),
            "limit": ast.Constant(value=limit),
        },
        "EvalSuggestionsSampleDiscovery",
    )
    return [DiscoveredTrace(trace_id=str(row[0]), days=int(row[1])) for row in rows]


def _hydrate(team: Team, trace_ids: Sequence[str], start: datetime, end: datetime) -> dict[str, list[tuple[Any, ...]]]:
    rows = run_ai_events_query(
        team,
        _HYDRATE_SQL,
        {
            "trace_ids": ast.Constant(value=list(trace_ids)),
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
            "max_input": ast.Constant(value=MAX_INPUT_MESSAGE_BYTES),
            "max_output": ast.Constant(value=MAX_OUTPUT_BYTES),
            "rows_per_trace": ast.Constant(value=EVENTS_PER_TRACE + 1),
            "max_rows": ast.Constant(value=len(trace_ids) * (EVENTS_PER_TRACE + 1)),
        },
        "EvalSuggestionsSampleHydration",
    )
    by_trace: defaultdict[str, list[tuple[Any, ...]]] = defaultdict(list)
    for row in rows:
        by_trace[str(row[0])].append(row)
    return by_trace


def _assistant_text(raw: str) -> str:
    """The text of an assistant message as raw JSON, or "" for any other message."""
    try:
        message = json.loads(raw) if raw else None
    except ValueError:
        return ""
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return ""
    content = message.get("content")
    if isinstance(content, list):
        content = " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content or "")


def _sampled_trace(
    trace_id: str, rows: list[tuple[Any, ...]], *, held_out: bool, spans_days: bool, segment_keys: Sequence[str]
) -> SampledTrace | None:
    # A trace with more events than the cap would be graded on part of its history, which can hide a failure.
    if len(rows) > EVENTS_PER_TRACE:
        return None
    rows = sorted(rows, key=lambda row: row[3])
    events: list[LLMTraceEvent] = []
    previous_replies: list[str] = []
    generations: list[tuple[LLMTraceEvent, int, bool]] = []
    final_output_too_long = False
    for (
        _,
        event_uuid,
        event,
        timestamp,
        _distinct_id,
        properties,
        last_input,
        user_messages,
        has_tool_results,
        output_choices,
        output,
        output_too_long,
        previous_message,
    ) in rows:
        merged = merge_heavy_properties(
            properties, {"input": last_input, "output_choices": output_choices, "output": output}
        )
        trace_event = LLMTraceEvent(
            id=str(event_uuid), event=str(event), createdAt=timestamp.isoformat(), properties=merged
        )
        events.append(trace_event)
        if event == "$ai_generation":
            generations.append((trace_event, int(user_messages or 0), bool(has_tool_results)))
            final_output_too_long = bool(output_too_long)
            previous_replies.append(_assistant_text(previous_message))
    # A final answer too long to read would leave the checks grading an earlier step as the answer.
    if not generations or final_output_too_long:
        return None

    def text(event: LLMTraceEvent, side: str) -> str:
        built = build_hog_event_global(event.event, event.properties, event_uuid=event.id, timestamp=event.createdAt)
        return str(built[f"{side}_text"])

    final_text = next((t for t in (text(g, "output") for g, _, _ in reversed(generations)) if t.strip()), "")
    last_generation = generations[-1][0]
    raw_segments = {
        key: str(last_generation.properties[key])
        for key in segment_keys
        if last_generation.properties.get(key) not in (None, "")
    }
    segment_values: dict[str, frozenset[str]] = {
        key: frozenset(
            normalize_segment_value(g.properties[key])
            for g, _, _ in generations
            if g.properties.get(key) not in (None, "")
        )
        for key in segment_keys
    }
    first = generations[0][0]
    # The reply the user answered, so a correction reads against what the assistant said before it.
    before = previous_replies[0][-TURN_TEXT_CHARS:]
    return SampledTrace(
        trace=LLMTrace(
            id=trace_id,
            createdAt=events[0].createdAt,
            distinctId=str(rows[0][4]),
            events=events,
        ),
        held_out=held_out,
        spans_days=spans_days,
        segments={key: normalize_segment_value(value) for key, value in raw_segments.items()},
        segment_values={key: values for key, values in segment_values.items() if values},
        raw_segment_values={
            key: values
            for key in segment_keys
            if (
                values := frozenset(
                    str(g.properties[key]) for g, _, _ in generations if g.properties.get(key) not in (None, "")
                )
            )
        },
        raw_segments=raw_segments,
        final_text=final_text,
        turn_text=(f"Assistant: {before}\n\n" if before else "")
        + f"User: {text(first, 'input')[-TURN_TEXT_CHARS:]}\n\nAssistant: {final_text[:TURN_TEXT_CHARS]}",
        user_messages=max(user_messages for _, user_messages, _ in generations),
        has_tool_results=any(tool_results for _, _, tool_results in generations),
        input_tokens=sum(float(g.properties.get("$ai_input_tokens") or 0) for g, _, _ in generations),
    )


def fetch_sample(team: Team, window: ProfileWindow, profile: TeamProfile) -> TraceSample:
    bucket = held_out_bucket(profile)
    if bucket is None:
        main = _discover(team, window.start, window.end, profile.traces, MAIN_SAMPLE_TRACES)
        held: list[DiscoveredTrace] = []
    else:
        held_start, held_end = window.end - timedelta(days=bucket + 1), window.end - timedelta(days=bucket)
        held_traces = profile.traces_by_days_ago.get(bucket, 0)
        main = _discover(team, window.start, held_start, profile.traces - held_traces, MAIN_SAMPLE_TRACES)
        main_ids = {trace.trace_id for trace in main}
        # A trace that runs across the boundary is discovered on both sides, and hydration reads all of it
        # for each, so keeping it in both would re-test a check on a trace it was measured on.
        held = [
            trace
            for trace in _discover(team, held_start, held_end, held_traces, HELD_OUT_SAMPLE_TRACES)
            if trace.trace_id not in main_ids
        ]

    discovered = [(trace, False) for trace in main] + [(trace, True) for trace in held]
    rows = (
        _hydrate(team, [trace.trace_id for trace, _ in discovered], window.start - timedelta(days=1), window.end)
        if discovered
        else {}
    )
    segment_keys = sorted(profile.segments)
    sample: dict[bool, list[SampledTrace]] = {False: [], True: []}
    for trace, is_held_out in discovered:
        if trace.trace_id not in rows:
            continue
        sampled = _sampled_trace(
            trace.trace_id,
            rows[trace.trace_id],
            held_out=is_held_out,
            spans_days=trace.days > 1,
            segment_keys=segment_keys,
        )
        if sampled is not None:
            sample[is_held_out].append(sampled)
    return TraceSample(main=sample[False], held_out=sample[True])


def structured_outputs(traces: Sequence[SampledTrace]) -> list[StructuredOutput]:
    outputs = []
    for sampled in traces:
        parsed = parse_structured(sampled.final_text)
        if parsed is not None:
            outputs.append(
                StructuredOutput(
                    trace_id=sampled.trace.id, segments=sampled.segments, fields=short_string_fields(parsed)
                )
            )
    return outputs


@frozen
class Outcome:
    trace_id: str
    # None when the check did not apply to the trace, or could not run on it.
    failed: bool | None
    reasoning: str


@frozen
class Measurement:
    check: AdaptedCheck
    main: list[Outcome]
    held_out: list[Outcome]


def run_check(bytecode: list[Any], traces: Sequence[SampledTrace]) -> list[Outcome]:
    outcomes = []
    for sampled in traces:
        globals_dict = build_trace_hog_globals(sampled.trace, sampled.trace.id, bytecode=bytecode)
        result = execute_hog_eval_bytecode(bytecode, globals_dict, allows_na=True)
        verdict = result.get("verdict") if not result.get("error") else None
        outcomes.append(
            Outcome(
                trace_id=sampled.trace.id,
                failed=None if verdict is None else verdict is False,
                reasoning=str(result.get("reasoning") or result.get("error") or ""),
            )
        )
    return outcomes


def measure(checks: Sequence[AdaptedCheck], sample: TraceSample) -> list[Measurement]:
    measurements = []
    for check in checks:
        bytecode = compile_check(check)
        measurements.append(
            Measurement(
                check=check, main=run_check(bytecode, sample.main), held_out=run_check(bytecode, sample.held_out)
            )
        )
    return measurements
