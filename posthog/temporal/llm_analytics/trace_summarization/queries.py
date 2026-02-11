"""ClickHouse queries for trace summarization.

Simple, direct queries that avoid expensive JOINs (e.g. person table)
which can OOM ClickHouse for teams with large AI traces.
"""

from datetime import UTC, datetime
from typing import Any

import orjson

from posthog.schema import LLMTrace, LLMTraceEvent, LLMTracePerson

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team
from posthog.temporal.llm_analytics.trace_summarization.constants import AI_EVENT_TYPES, TRACE_CAPTURE_RANGE

_TRACE_EVENTS_QUERY = """
    SELECT
        uuid, event, timestamp, properties,
        ai_properties.ai_input_state AS _ai_input_state,
        ai_properties.ai_output_state AS _ai_output_state,
        ai_properties.ai_input AS _ai_input,
        ai_properties.ai_output AS _ai_output,
        ai_properties.ai_output_choices AS _ai_output_choices,
        ai_properties.ai_tools AS _ai_tools
    FROM events
    WHERE event IN {event_types}
      AND timestamp >= toDateTime({start_ts}, 'UTC')
      AND timestamp < toDateTime({end_ts}, 'UTC')
      AND properties.$ai_trace_id = {trace_id}
    ORDER BY timestamp
"""

_AI_PROPERTY_COLUMNS = {
    "$ai_input_state": "_ai_input_state",
    "$ai_output_state": "_ai_output_state",
    "$ai_input": "_ai_input",
    "$ai_output": "_ai_output",
    "$ai_output_choices": "_ai_output_choices",
    "$ai_tools": "_ai_tools",
}


def fetch_trace(team: Team, trace_id: str, window_start: str, window_end: str) -> LLMTrace | None:
    """Fetch trace events with a simple query — no person JOIN, no aggregations.

    Returns an LLMTrace or None if no events found. The $ai_trace meta-event
    is used to populate trace-level fields (traceName, inputState, outputState)
    but is excluded from the events list (matching TraceQueryRunner behavior).
    """
    start_dt = datetime.fromisoformat(window_start).astimezone(UTC) - TRACE_CAPTURE_RANGE
    end_dt = datetime.fromisoformat(window_end).astimezone(UTC) + TRACE_CAPTURE_RANGE

    query = parse_select(_TRACE_EVENTS_QUERY)
    result = execute_hogql_query(
        query_type="SummarizationTraceFetch",
        query=query,
        placeholders={
            "event_types": ast.Tuple(exprs=[ast.Constant(value=e) for e in AI_EVENT_TYPES]),
            "start_ts": ast.Constant(value=start_dt.strftime("%Y-%m-%d %H:%M:%S")),
            "end_ts": ast.Constant(value=end_dt.strftime("%Y-%m-%d %H:%M:%S")),
            "trace_id": ast.Constant(value=trace_id),
        },
        team=team,
        limit_context=LimitContext.QUERY_ASYNC,
    )

    if not result.results:
        return None

    events: list[LLMTraceEvent] = []
    trace_name: str | None = None
    input_state: Any = None
    output_state: Any = None
    first_timestamp: str | None = None

    for row in result.results:
        event_uuid, event_name, event_timestamp, event_properties, *ai_cols = row
        if first_timestamp is None:
            first_timestamp = event_timestamp.isoformat()

        props = orjson.loads(event_properties) if isinstance(event_properties, str) else event_properties

        # Merge large AI properties from the separate table back into props (dual-read)
        for prop_name, col_idx in zip(_AI_PROPERTY_COLUMNS, range(len(ai_cols))):
            val = ai_cols[col_idx]
            if val and not props.get(prop_name):
                try:
                    props[prop_name] = orjson.loads(val)
                except (orjson.JSONDecodeError, TypeError):
                    props[prop_name] = val

        if event_name == "$ai_trace":
            trace_name = props.get("$ai_span_name") or props.get("$ai_trace_name")
            raw_input = props.get("$ai_input_state")
            if isinstance(raw_input, str):
                try:
                    input_state = orjson.loads(raw_input)
                except (orjson.JSONDecodeError, TypeError):
                    input_state = None
            else:
                input_state = raw_input

            raw_output = props.get("$ai_output_state")
            if isinstance(raw_output, str):
                try:
                    output_state = orjson.loads(raw_output)
                except (orjson.JSONDecodeError, TypeError):
                    output_state = None
            else:
                output_state = raw_output
            continue

        events.append(
            LLMTraceEvent(
                id=str(event_uuid),
                event=event_name,
                createdAt=event_timestamp.isoformat(),
                properties=props,
            )
        )

    if not events:
        return None

    return LLMTrace(
        id=trace_id,
        createdAt=first_timestamp or events[0].createdAt,
        distinctId="",
        traceName=trace_name,
        inputState=input_state,
        outputState=output_state,
        events=events,
        person=LLMTracePerson(uuid="", distinct_id="", created_at=first_timestamp or "", properties={}),
    )
