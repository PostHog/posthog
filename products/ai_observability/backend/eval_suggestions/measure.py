"""Stage 4: fetch one bounded sample of a team's traces and run every applicable Hog check on it.

The sample is spread over the window by trace id hash rather than taken from the latest traces, and the
most recent day with traffic is held out so stage 6 can re-test each check on traces it was not picked on.
"""

import re
import json
import math
import time
from collections.abc import Sequence
from dataclasses import fields
from datetime import datetime, timedelta
from typing import Any

import orjson

from posthog.schema import LLMTrace, LLMTraceEvent

from posthog.dataclasses import frozen
from posthog.hogql_queries.ai.utils import merge_heavy_properties
from posthog.models.team import Team

from products.ai_observability.backend.logic.eval_suggestions.profile_queries import ProfileWindow
from products.ai_observability.backend.logic.eval_suggestions.sample_queries import (
    EVENTS_PER_TRACE,
    TURN_TEXT_CHARS,
    DiscoveredTrace,
    HydratedEventRow,
    load_discovered_traces,
    load_hydrated_events,
)
from products.ai_observability.backend.logic.evaluations.event_io import extract_event_io
from products.ai_observability.backend.logic.evaluations.hog_runtime import (
    build_hog_event_global,
    build_trace_hog_globals,
    execute_hog_eval_bytecode,
)

from .adapters import AdaptedCheck, compile_check
from .profile import (
    StructuredOutput,
    TeamProfile,
    normalize_segment_value,
    parse_structured,
    segment_text,
    short_string_fields,
)

MAIN_SAMPLE_TRACES = 250
HELD_OUT_SAMPLE_TRACES = 150
# Discovery groups only a slice of the window's traces, sized so the hash order still has room to choose.
DISCOVERY_OVERSAMPLE = 20
# Hydration reads traces in batches and stops once the sample holds this much text, since each row can be
# ~130 KB and the per-column caps alone would let a sample grow to gigabytes.
MAX_SAMPLE_BYTES = 64 * 1024 * 1024
HYDRATE_BATCH_TRACES = 50
ROLE_LABEL = re.compile(r"^(assistant|ai|model):\s*", re.IGNORECASE)
TOOL_CALL_TYPES = frozenset({"tool_use", "function_call", "tool_call", "tool-call"})
MAX_REASONING_CHARS = 2000


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


def _discover(
    team: Team, start: datetime, end: datetime, expected_traces: int, limit: int, read: ProfileWindow
) -> list[DiscoveredTrace]:
    per_mille = (
        1000
        if expected_traces <= limit * DISCOVERY_OVERSAMPLE
        else math.ceil(1000 * limit * DISCOVERY_OVERSAMPLE / expected_traces)
    )
    return load_discovered_traces(team, start=start, end=end, read=read, per_mille=per_mille, limit=limit)


def _has_tool_call(value: Any) -> bool:
    """Whether a parsed output holds a tool call, the same shapes the checks' `collect_calls` reads."""
    if isinstance(value, list):
        return any(_has_tool_call(child) for child in value)
    if not isinstance(value, dict):
        return False
    function = value.get("function")
    if isinstance(function, dict) and function.get("name") is not None:
        return True
    kind = value.get("type")
    if isinstance(kind, str) and kind in TOOL_CALL_TYPES and (value.get("toolName") or value.get("name")) is not None:
        return True
    return any(_has_tool_call(child) for child in value.values())


def _calls_tools(generation: LLMTraceEvent) -> bool:
    """Whether a generation's output asks for tools, which makes it a step of the turn and not its answer."""
    output = extract_event_io(generation.event, generation.properties).output_raw
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except ValueError:
            return False
    return _has_tool_call(output)


def _rendered_text(event: LLMTraceEvent, side: str) -> str:
    built = build_hog_event_global(event.event, event.properties, event_uuid=event.id, timestamp=event.createdAt)
    return str(built[f"{side}_text"])


def final_answer(generations: Sequence[LLMTraceEvent]) -> str:
    """The last generation with text that is not a tool call, without the role label the renderer adds.

    Checks pick the answer in Hog with `adapters._FINAL_TEXT`, and one test case list holds the two to the same result.
    """
    return next(
        (
            ROLE_LABEL.sub("", text)
            for text in (_rendered_text(g, "output") for g in reversed(generations) if not _calls_tools(g))
            if text.strip()
        ),
        "",
    )


def _tokens(value: Any) -> float:
    """Token counts as sent, where a malformed value counts as none rather than failing the sample."""
    try:
        return max(float(value or 0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _sampled_trace(
    trace_id: str, rows: list[HydratedEventRow], *, held_out: bool, spans_days: bool, segment_keys: Sequence[str]
) -> SampledTrace | None:
    # A trace with more events than the cap would be graded on part of its history, which can hide a failure.
    if len(rows) > EVENTS_PER_TRACE:
        return None
    rows = sorted(rows, key=lambda row: row.timestamp)
    events: list[LLMTraceEvent] = []
    previous_replies: list[str] = []
    generations: list[tuple[LLMTraceEvent, int, bool]] = []
    for row in rows:
        # Any event cut to fit (a long output, state or metadata) would grade the trace on part of its history.
        if row.unreadable:
            return None
        merged = merge_heavy_properties(
            row.properties,
            {
                "input": row.last_input,
                "output_choices": row.output_choices,
                "output": row.output,
                "input_state": row.input_state,
                "output_state": row.output_state,
            },
        )
        try:
            # Values nested deeper than orjson writes would hit Python's recursion limit in the checks.
            orjson.dumps(merged)
        except orjson.JSONEncodeError:
            return None
        trace_event = LLMTraceEvent(
            id=row.event_uuid, event=row.event, createdAt=row.timestamp.isoformat(), properties=merged
        )
        events.append(trace_event)
        if row.event == "$ai_generation":
            generations.append((trace_event, row.user_messages, row.has_tool_results))
            previous_replies.append(row.previous_reply)
    if not generations:
        return None

    try:
        final_text = final_answer([g for g, _, _ in generations])
    except RecursionError:
        # An output string nested deeper than orjson parses stays raw, and Python can't parse it either.
        return None
    last_generation = generations[-1][0]
    last_segments = {
        key: segment_text(last_generation.properties[key])
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
    before = previous_replies[0]
    return SampledTrace(
        trace=LLMTrace(
            id=trace_id,
            createdAt=events[0].createdAt,
            distinctId=rows[0].distinct_id,
            events=events,
        ),
        held_out=held_out,
        spans_days=spans_days,
        segments={key: normalize_segment_value(value) for key, value in last_segments.items()},
        segment_values={key: values for key, values in segment_values.items() if values},
        raw_segment_values={
            key: values
            for key in segment_keys
            if (
                values := frozenset(
                    segment_text(g.properties[key])
                    for g, _, _ in generations
                    if g.properties.get(key) not in (None, "")
                )
            )
        },
        final_text=final_text,
        turn_text=(f"Assistant: {before}\n\n" if before else "")
        + f"User: {_rendered_text(first, 'input')[-TURN_TEXT_CHARS:]}\n\nAssistant: {final_text[:TURN_TEXT_CHARS]}",
        user_messages=max(user_messages for _, user_messages, _ in generations),
        has_tool_results=any(tool_results for _, _, tool_results in generations),
        input_tokens=sum(_tokens(g.properties.get("$ai_input_tokens")) for g, _, _ in generations),
    )


@frozen
class SampleRef:
    """A sampled trace by id, which later stages hydrate again so trace content never leaves the process."""

    trace_id: str
    # Distinct days the trace has generations on.
    days: int
    held_out: bool


def discover_sample(team: Team, window: ProfileWindow, profile: TeamProfile) -> list[SampleRef]:
    read = _read_span(window)
    bucket = held_out_bucket(profile)
    if bucket is None:
        main = _discover(team, window.start, window.end, profile.traces, MAIN_SAMPLE_TRACES, read)
        held: list[DiscoveredTrace] = []
    else:
        held_start, held_end = window.end - timedelta(days=bucket + 1), window.end - timedelta(days=bucket)
        held_traces = profile.traces_by_days_ago.get(bucket, 0)
        main = _discover(team, window.start, held_start, profile.traces - held_traces, MAIN_SAMPLE_TRACES, read)
        main_ids = {trace.trace_id for trace in main}
        # A trace that runs across the boundary is discovered on both sides, and hydration reads all of it
        # for each, so keeping it in both would re-test a check on a trace it was measured on.
        held = [
            trace
            for trace in _discover(team, held_start, held_end, held_traces, HELD_OUT_SAMPLE_TRACES, read)
            if trace.trace_id not in main_ids
        ]
    return [SampleRef(trace_id=t.trace_id, days=t.days, held_out=False) for t in main] + [
        SampleRef(trace_id=t.trace_id, days=t.days, held_out=True) for t in held
    ]


def hydrate_sample(
    team: Team, window: ProfileWindow, segment_keys: Sequence[str], refs: Sequence[SampleRef]
) -> TraceSample:
    read = _read_span(window)
    held_share = HELD_OUT_SAMPLE_TRACES / (MAIN_SAMPLE_TRACES + HELD_OUT_SAMPLE_TRACES)
    keys = sorted(segment_keys)
    return TraceSample(
        main=_hydrated(
            team, [r for r in refs if not r.held_out], read, keys, budget=MAX_SAMPLE_BYTES * (1 - held_share)
        ),
        held_out=_hydrated(team, [r for r in refs if r.held_out], read, keys, budget=MAX_SAMPLE_BYTES * held_share),
    )


def fetch_sample(team: Team, window: ProfileWindow, profile: TeamProfile) -> TraceSample:
    return hydrate_sample(team, window, list(profile.segments), discover_sample(team, window, profile))


def _read_span(window: ProfileWindow) -> ProfileWindow:
    # Hydration reads a day before the window too, for traces that started before it.
    return ProfileWindow(start=window.start - timedelta(days=1), end=window.end)


def _row_bytes(row: HydratedEventRow) -> int:
    return sum(len(value) for field in fields(row) if isinstance(value := getattr(row, field.name), str))


def _hydrated(
    team: Team,
    refs: Sequence[SampleRef],
    read: ProfileWindow,
    segment_keys: Sequence[str],
    *,
    budget: float,
) -> list[SampledTrace]:
    """Hydrate traces batch by batch in discovery order, and stop once the rows read pass `budget` bytes."""
    sampled_traces: list[SampledTrace] = []
    used = 0
    for start in range(0, len(refs), HYDRATE_BATCH_TRACES):
        if used >= budget:
            break
        batch = refs[start : start + HYDRATE_BATCH_TRACES]
        rows = load_hydrated_events(team, [trace.trace_id for trace in batch], read)
        used += sum(_row_bytes(row) for trace_rows in rows.values() for row in trace_rows)
        for trace in batch:
            if trace.trace_id not in rows:
                continue
            sampled = _sampled_trace(
                trace.trace_id,
                rows[trace.trace_id],
                held_out=trace.held_out,
                spans_days=trace.days > 1,
                segment_keys=segment_keys,
            )
            if sampled is not None:
                sampled_traces.append(sampled)
    return sampled_traces


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


def run_check(bytecode: list[Any], traces: Sequence[SampledTrace], deadline: float | None = None) -> list[Outcome]:
    """Outcomes in trace order. Past `deadline`, a time.monotonic() value, it stops and returns the ones so far."""
    outcomes = []
    for sampled in traces:
        # Each trace can run up to the 10s Hog limit, so a long sample would outlast the activity.
        if deadline is not None and time.monotonic() >= deadline:
            break
        globals_dict = build_trace_hog_globals(sampled.trace, sampled.trace.id, bytecode=bytecode)
        result = execute_hog_eval_bytecode(bytecode, globals_dict, allows_na=True)
        verdict = result.get("verdict") if not result.get("error") else None
        outcomes.append(
            Outcome(
                trace_id=sampled.trace.id,
                failed=None if verdict is None else verdict is False,
                # Kept for every sampled trace, while evidence shows a few lines.
                reasoning=str(result.get("reasoning") or result.get("error") or "")[:MAX_REASONING_CHARS],
            )
        )
    return outcomes


def measure(checks: Sequence[AdaptedCheck], sample: TraceSample, deadline: float | None = None) -> list[Measurement]:
    measurements = []
    for check in checks:
        bytecode = compile_check(check)
        measurements.append(
            Measurement(
                check=check,
                main=run_check(bytecode, sample.main, deadline),
                held_out=run_check(bytecode, sample.held_out, deadline),
            )
        )
    return measurements
