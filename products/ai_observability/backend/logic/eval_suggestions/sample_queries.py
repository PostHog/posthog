from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime

from posthog.hogql import ast

from posthog.dataclasses import frozen
from posthog.models.team import Team

from .profile_queries import ProfileWindow
from .queries import run_ai_events_query, run_query

# Hydration reads every event of a trace, and a check needs a trace's whole history, so discovery only picks
# traces with at most this many events. Longer ones (a shared or runaway trace id) cost the most to read.
EVENTS_PER_TRACE = 40
MAX_OUTPUT_BYTES = 16384
MAX_INPUT_MESSAGE_BYTES = 8192
# Agent frameworks such as LangGraph send their whole graph state on every span. Checks don't read a span's state, so
# a long one is cut rather than dropping the trace, which would leave only short traces in the sample.
MAX_STATE_BYTES = 16384
# Custom metadata past this size marks the event unreadable, which keeps the sample's memory bounded.
MAX_PROPERTIES_BYTES = 65536
# Screening reads at most 3000 characters, so each part of a turn gets a third.
TURN_TEXT_CHARS = 1000

_DISCOVER_SQL = """
SELECT
    toString(properties.$ai_trace_id) AS trace_id,
    uniq(toDate(timestamp)) AS days
FROM events
WHERE event IN ('$ai_generation', '$ai_span', '$ai_embedding')
  AND timestamp >= {read_start}
  AND timestamp < {read_end}
  AND notEmpty(toString(properties.$ai_trace_id))
  AND length(toString(properties.$ai_trace_id)) <= 256
  AND cityHash64(toString(properties.$ai_trace_id)) % 1000 < {per_mille}
GROUP BY trace_id
HAVING countIf(event = '$ai_generation' AND timestamp >= {start} AND timestamp < {end}) > 0
   AND count() <= {max_events}
ORDER BY cityHash64(trace_id)
LIMIT {limit}
"""

# Only the last two messages of each input are read: the last is the user's message for the first call of a turn,
# and the one before it is the assistant reply the user answers. Full histories cost far more than checks need.
# The query keeps only the end of that reply's text (string content, content blocks, OTel or Gemini parts),
# since a cut in the raw JSON would make it unreadable.
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
    unreadable,
    previous_reply,
    input_state,
    output_state
FROM (
    SELECT
        trace_id,
        toString(uuid) AS event_uuid,
        event,
        timestamp,
        distinct_id,
        if(length(ai_events.properties) <= {max_properties}, ai_events.properties, '{}') AS properties,
        if(startsWith(input, '['), concat('[', left(JSONExtractRaw(input, -1), {max_input}), ']'), left(input, {max_input})) AS last_input,
        if(startsWith(input, '[') AND JSONLength(input) >= 2, JSONExtractRaw(input, -2), '') AS previous_raw,
        if(
            JSONExtractString(previous_raw, 'role') IN ('assistant', 'model'),
            right(
                arrayStringConcat(
                    arrayFilter(
                        part -> part != '',
                        arrayConcat(
                            [JSONExtractString(previous_raw, 'content')],
                            arrayMap(block -> JSONExtractString(block, 'text'), JSONExtractArrayRaw(previous_raw, 'content')),
                            arrayMap(
                                block -> if(JSONHas(block, 'content'), JSONExtractString(block, 'content'), JSONExtractString(block, 'text')),
                                JSONExtractArrayRaw(previous_raw, 'parts')
                            )
                        )
                    ),
                    ' '
                ),
                {turn_chars}
            ),
            ''
        ) AS previous_reply,
        countMatches(input, '"role":[[:space:]]*"user"') AS user_messages,
        match(input, '"role":[[:space:]]*"tool"|"type":[[:space:]]*"(tool_result|function_call_output)"') AS has_tool_results,
        if(length(output_choices) <= {max_output}, output_choices, '') AS output_choices,
        if(length(output) <= {max_output}, output, '') AS output,
        left(input_state, {max_state}) AS input_state,
        left(output_state, {max_state}) AS output_state,
        length(ai_events.output_choices) > {max_output}
            OR length(ai_events.output) > {max_output}
            -- A generation with no other output answers through its state, so a cut there would grade half an answer.
            OR (event = '$ai_generation' AND empty(coalesce(ai_events.output_choices, ''))
                AND empty(coalesce(ai_events.output, ''))
                AND length(ai_events.output_state) > {max_state})
            OR length(ai_events.properties) > {max_properties} AS unreadable
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
class DiscoveredTrace:
    trace_id: str
    # Distinct days the trace has generations on.
    days: int


@frozen
class HydratedEventRow:
    """One event of a sampled trace, with its heavy columns cut to the caps above."""

    trace_id: str
    event_uuid: str
    event: str
    timestamp: datetime
    distinct_id: str
    properties: str
    last_input: str
    user_messages: int
    has_tool_results: bool
    output_choices: str
    output: str
    unreadable: bool
    previous_reply: str
    input_state: str
    output_state: str


def load_discovered_traces(
    team: Team, *, start: datetime, end: datetime, read: ProfileWindow, per_mille: int, limit: int
) -> list[DiscoveredTrace]:
    """Traces with a generation between `start` and `end`, counting their events over the whole span hydration reads."""
    rows = run_query(
        team,
        _DISCOVER_SQL,
        {
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
            "read_start": ast.Constant(value=read.start),
            "read_end": ast.Constant(value=read.end),
            "per_mille": ast.Constant(value=per_mille),
            "max_events": ast.Constant(value=EVENTS_PER_TRACE),
            "limit": ast.Constant(value=limit),
        },
        "EvalSuggestionsSampleDiscovery",
    )
    return [DiscoveredTrace(trace_id=str(row[0]), days=int(row[1])) for row in rows]


def load_hydrated_events(
    team: Team, trace_ids: Sequence[str], read: ProfileWindow
) -> dict[str, list[HydratedEventRow]]:
    """The events of each trace, newest first, keyed by trace id."""
    rows = run_ai_events_query(
        team,
        _HYDRATE_SQL,
        {
            "trace_ids": ast.Constant(value=list(trace_ids)),
            "start": ast.Constant(value=read.start),
            "end": ast.Constant(value=read.end),
            "max_input": ast.Constant(value=MAX_INPUT_MESSAGE_BYTES),
            "max_output": ast.Constant(value=MAX_OUTPUT_BYTES),
            "max_state": ast.Constant(value=MAX_STATE_BYTES),
            "max_properties": ast.Constant(value=MAX_PROPERTIES_BYTES),
            "turn_chars": ast.Constant(value=TURN_TEXT_CHARS),
            "rows_per_trace": ast.Constant(value=EVENTS_PER_TRACE + 1),
            "max_rows": ast.Constant(value=len(trace_ids) * (EVENTS_PER_TRACE + 1)),
        },
        "EvalSuggestionsSampleHydration",
    )
    by_trace: defaultdict[str, list[HydratedEventRow]] = defaultdict(list)
    for row in rows:
        by_trace[str(row[0])].append(
            HydratedEventRow(
                trace_id=str(row[0]),
                event_uuid=str(row[1]),
                event=str(row[2]),
                timestamp=row[3],
                distinct_id=str(row[4]),
                properties=row[5],
                last_input=row[6],
                user_messages=int(row[7] or 0),
                has_tool_results=bool(row[8]),
                output_choices=row[9],
                output=row[10],
                unreadable=bool(row[11]),
                previous_reply=str(row[12] or ""),
                input_state=row[13],
                output_state=row[14],
            )
        )
    return by_trace
