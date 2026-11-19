from collections.abc import Callable

from posthog.hogql import ast

from posthog.dataclasses import frozen


@frozen
class TraceColumns:
    event: ast.Expr
    latency: ast.Expr
    parent_id: ast.Expr
    trace_id: ast.Expr
    is_error: ast.Expr
    distinct_id: ast.Expr
    ingestion_source: ast.Expr


def _field(*chain: str) -> ast.Field:
    return ast.Field(chain=list(chain))


AI_EVENTS_COLUMNS = TraceColumns(
    event=_field("event"),
    latency=_field("latency"),
    parent_id=_field("parent_id"),
    trace_id=_field("trace_id"),
    is_error=ast.Call(name="if", args=[_field("is_error"), ast.Constant(value="true"), ast.Constant(value="false")]),
    distinct_id=_field("distinct_id"),
    ingestion_source=_field("properties", "$ai_ingestion_source"),
)

EVENTS_COLUMNS = TraceColumns(
    event=_field("event"),
    latency=ast.Call(name="toFloat", args=[_field("properties", "$ai_latency")]),
    parent_id=_field("properties", "$ai_parent_id"),
    trace_id=_field("properties", "$ai_trace_id"),
    is_error=_field("properties", "$ai_is_error"),
    distinct_id=_field("distinct_id"),
    ingestion_source=_field("properties", "$ai_ingestion_source"),
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


def trace_errored(columns: TraceColumns, aggregate: Aggregate) -> ast.Expr:
    flagged = _compare(ast.CompareOperationOp.Eq, columns.is_error, _constant("true"))
    return _compare(ast.CompareOperationOp.Gt, aggregate("countIf", [flagged]), _constant(0))


def event_identified(columns: TraceColumns) -> ast.Expr:
    return ast.And(
        exprs=[
            _compare(ast.CompareOperationOp.NotEq, columns.distinct_id, _if_null(columns.trace_id, "")),
            _compare(ast.CompareOperationOp.NotEq, _if_null(columns.ingestion_source, ""), _constant("otel")),
        ]
    )
