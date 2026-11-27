from collections.abc import Callable, Sequence

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.dataclasses import frozen

NODE_EVENT_NAMES = ("$ai_span", "$ai_generation", "$ai_embedding")
TRACE_EVENT_NAMES = ("$ai_trace", *NODE_EVENT_NAMES)
BILLED_EVENT_NAMES = ("$ai_generation", "$ai_embedding")


@frozen
class TraceColumns:
    event: ast.Expr
    timestamp: ast.Expr
    latency: ast.Expr
    parent_id: ast.Expr
    trace_id: ast.Expr
    is_error: ast.Expr
    distinct_id: ast.Expr
    person: ast.Expr
    session_id: ast.Expr
    properties: ast.Expr
    ingestion_source: ast.Expr
    total_cost: ast.Expr


def _field(*chain: str) -> ast.Field:
    return ast.Field(chain=list(chain))


def _finite(value: ast.Expr) -> ast.Call:
    # An SDK can send "Infinity" as a latency or a cost, and one such event would make the whole trace's sum or max
    # infinite, so it reads as missing instead.
    return ast.Call(name="if", args=[ast.Call(name="isFinite", args=[value]), value, ast.Constant(value=None)])


# On ai_events a trace's person is named by its distinct id, which the trace view and the list resolve to a person.
AI_EVENTS_COLUMNS = TraceColumns(
    event=_field("event"),
    timestamp=_field("timestamp"),
    latency=_finite(_field("latency")),
    parent_id=_field("parent_id"),
    trace_id=_field("trace_id"),
    is_error=ast.Call(name="if", args=[_field("is_error"), ast.Constant(value="true"), ast.Constant(value="false")]),
    distinct_id=_field("distinct_id"),
    person=_field("distinct_id"),
    session_id=_field("session_id"),
    properties=_field("properties"),
    ingestion_source=_field("properties", "$ai_ingestion_source"),
    total_cost=_finite(_field("total_cost_usd")),
)

EVENTS_COLUMNS = TraceColumns(
    event=_field("event"),
    timestamp=_field("timestamp"),
    latency=_finite(ast.Call(name="toFloat", args=[_field("properties", "$ai_latency")])),
    parent_id=_field("properties", "$ai_parent_id"),
    trace_id=_field("properties", "$ai_trace_id"),
    is_error=_field("properties", "$ai_is_error"),
    distinct_id=_field("distinct_id"),
    person=_field("person_id"),
    session_id=_field("properties", "$ai_session_id"),
    properties=_field("properties"),
    ingestion_source=_field("properties", "$ai_ingestion_source"),
    total_cost=_finite(ast.Call(name="toFloat", args=[_field("properties", "$ai_total_cost_usd")])),
)

Aggregate = Callable[[str, list[ast.Expr]], ast.Expr]


def grouped(name: str, args: list[ast.Expr]) -> ast.Expr:
    return ast.Call(name=name, args=args)


def over_trace(trace_id: ast.Expr) -> Aggregate:
    def windowed(name: str, args: list[ast.Expr]) -> ast.Expr:
        return ast.WindowFunction(name=name, exprs=args, over_expr=ast.WindowExpr(partition_by=[trace_id]))

    return windowed


def _constant(value: str | int | None) -> ast.Constant:
    return ast.Constant(value=value)


def _compare(op: ast.CompareOperationOp, left: ast.Expr, right: ast.Expr) -> ast.CompareOperation:
    return ast.CompareOperation(op=op, left=left, right=right)


def _event_in(columns: TraceColumns, names: tuple[str, ...]) -> ast.CompareOperation:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In, left=columns.event, right=ast.Tuple(exprs=[_constant(name) for name in names])
    )


def _if(condition: ast.Expr, then: ast.Expr, otherwise: ast.Expr) -> ast.Call:
    return ast.Call(name="if", args=[condition, then, otherwise])


def _if_null(value: ast.Expr, fallback: str) -> ast.Call:
    return ast.Call(name="ifNull", args=[value, _constant(fallback)])


def trace_latency(columns: TraceColumns, aggregate: Aggregate) -> ast.Expr:
    """A root `$ai_trace` latency wins, because that event reports the whole trace's wall clock and its children are
    already inside it. A trace of only timed generations sums them, and any other trace sums its top-level events.
    NULL when no event has a positive latency."""
    eq, not_eq, gt = ast.CompareOperationOp.Eq, ast.CompareOperationOp.NotEq, ast.CompareOperationOp.Gt
    timed = _compare(gt, ast.Call(name="ifNull", args=[columns.latency, _constant(0)]), _constant(0))
    is_generation = _compare(eq, columns.event, _constant("$ai_generation"))
    is_root = _compare(eq, columns.event, _constant("$ai_trace"))
    is_top_level = ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=_if_null(columns.parent_id, ""),
        right=ast.Tuple(exprs=[_constant(""), columns.trace_id]),
    )

    root_latency = aggregate("maxIf", [columns.latency, ast.And(exprs=[is_root, timed])])
    timed_non_generations = aggregate(
        "countIf", [ast.And(exprs=[timed, _compare(not_eq, columns.event, _constant("$ai_generation"))])]
    )
    generation_sum = aggregate("sumIf", [columns.latency, is_generation])
    top_level_sum = aggregate("sumIf", [columns.latency, is_top_level])

    total = _if(
        _compare(gt, root_latency, _constant(0)),
        root_latency,
        _if(_compare(eq, timed_non_generations, _constant(0)), generation_sum, top_level_sum),
    )
    nothing_timed = _compare(eq, aggregate("countIf", [timed]), _constant(0))
    return ast.Call(name="round", args=[_if(nothing_timed, _constant(None), total), _constant(2)])


def event_errored(columns: TraceColumns) -> ast.Expr:
    return _compare(ast.CompareOperationOp.Eq, columns.is_error, _constant("true"))


def trace_errored(columns: TraceColumns, aggregate: Aggregate) -> ast.Expr:
    return _compare(ast.CompareOperationOp.Gt, aggregate("countIf", [event_errored(columns)]), _constant(0))


def error_message(columns: TraceColumns) -> ast.Expr:
    """The event's normalized error message as it was sent, NULL when the event has none."""
    # Where events store properties as a JSON string, `properties.$ai_error_normalized` keeps the JSON escapes, so a
    # message with a quote, a backslash or a newline would not equal the message as sent. JSONExtractString decodes it
    # there, and HogQL prints it as a read of the typed property where events store typed properties.
    message = ast.Call(name="JSONExtractString", args=[columns.properties, _constant("$ai_error_normalized")])
    return ast.Call(name="nullIf", args=[message, _constant("")])


def tool_names(columns: TraceColumns, property_name: str) -> ast.Expr:
    """The tool names a comma-separated property lists, in their order, each trimmed, without empty parts."""
    # Decoded like `error_message`, so a name with a quote or a backslash reads as it was sent in both events layouts.
    names = ast.Call(name="JSONExtractString", args=[columns.properties, _constant(property_name)])
    return parse_expr(
        "arrayFilter(x -> x != '', arrayMap(x -> trim(x), splitByChar(',', ifNull({names}, ''))))",
        placeholders={"names": names},
    )


def trace_cost(columns: TraceColumns, aggregate: Aggregate) -> ast.Expr:
    """The trace's cost in USD over its billed events, NULL when none of them reports a cost."""
    return aggregate("sumIf", [columns.total_cost, _event_in(columns, BILLED_EVENT_NAMES)])


def trace_person_id(columns: TraceColumns, aggregate: Aggregate) -> ast.Expr:
    """The person the traces list shows for a trace: from the events with a distinct id, the root `$ai_trace` event's,
    else the earliest one's, and the smallest distinct id among events at the same time. Feedback and metric events
    never name it. NULL when no trace event has a distinct id."""
    has_person = ast.And(
        exprs=[
            _event_in(columns, TRACE_EVENT_NAMES),
            _compare(ast.CompareOperationOp.NotEq, columns.distinct_id, _constant("")),
        ]
    )
    not_root = _compare(ast.CompareOperationOp.NotEq, columns.event, _constant("$ai_trace"))
    return _if(
        _compare(ast.CompareOperationOp.Gt, aggregate("countIf", [has_person]), _constant(0)),
        aggregate(
            "argMinIf",
            [columns.person, ast.Tuple(exprs=[not_root, columns.timestamp, columns.distinct_id]), has_person],
        ),
        _constant(None),
    )


def event_has_session(columns: TraceColumns) -> ast.Expr:
    return _compare(ast.CompareOperationOp.NotEq, _if_null(columns.session_id, ""), _constant(""))


def trace_session_id(columns: TraceColumns, aggregate: Aggregate) -> ast.Expr:
    """The session a trace belongs to: the earliest trace event's non-empty session id, and the smallest one among
    events at the same time. NULL when no trace event carries one."""
    has_session = ast.And(exprs=[_event_in(columns, TRACE_EVENT_NAMES), event_has_session(columns)])
    earliest = aggregate(
        "argMinIf", [columns.session_id, ast.Tuple(exprs=[columns.timestamp, columns.session_id]), has_session]
    )
    return ast.Call(name="nullIf", args=[earliest, _constant("")])


def trace_session_ids(columns: TraceColumns, aggregate: Aggregate) -> ast.Expr:
    """Every session a trace belongs to: each non-empty session id any of its events carries. A trace whose events name
    two sessions belongs to both, and each of them counts it."""
    return aggregate("groupUniqArrayIf", [columns.session_id, event_has_session(columns)])


def names_session(columns: TraceColumns, session_ids: Sequence[str]) -> ast.Expr:
    """Whether an event carries one of the session ids, which by `trace_session_ids` puts its whole trace in that
    session. Reads narrow to the traces of such events before they group a trace's events."""
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In, left=columns.session_id, right=ast.Constant(value=list(session_ids))
    )


def not_impersonated() -> ast.Expr:
    """Whether an event was not sent while a support agent impersonated the user. Reads only the slim `properties`
    column on `posthog.ai_events`, but the whole properties JSON on the shared events table."""
    flag = _field("properties", "ai_support_impersonated")
    return ast.Or(
        exprs=[ast.Call(name="isNull", args=[flag]), _compare(ast.CompareOperationOp.NotEq, flag, _constant("true"))]
    )


def event_is_otel(columns: TraceColumns) -> ast.Expr:
    return _compare(ast.CompareOperationOp.Eq, _if_null(columns.ingestion_source, ""), _constant("otel"))


def event_identified(columns: TraceColumns) -> ast.Expr:
    return ast.And(
        exprs=[
            _compare(ast.CompareOperationOp.NotEq, columns.distinct_id, _if_null(columns.trace_id, "")),
            ast.Not(expr=event_is_otel(columns)),
        ]
    )


def event_anonymous(columns: TraceColumns) -> ast.Expr:
    # No OpenTelemetry clause: an OpenTelemetry event carries a distinct id derived from something other than the trace
    # id, so it counts as identified here.
    return _compare(ast.CompareOperationOp.Eq, columns.distinct_id, _if_null(columns.trace_id, ""))
