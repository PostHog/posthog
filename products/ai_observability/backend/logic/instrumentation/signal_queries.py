from posthog.hogql import ast

from products.ai_observability.backend.logic.traces.trace_expression_queries import TraceColumns, event_identified


def event_declines_session(columns: TraceColumns) -> ast.Expr:
    """An explicit null `$ai_session_id` says the workload finishes in one trace, an answer rather than a gap. JSONType
    reads absent and null alike, so JSONHas separates them, and an empty string (usually an unset variable) stays out."""
    key = ast.Constant(value="$ai_session_id")
    return ast.And(
        exprs=[
            ast.Call(name="JSONHas", args=[columns.properties, key]),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Call(name="JSONType", args=[columns.properties, key]),
                right=ast.Constant(value="Null"),
            ),
        ]
    )


def sdk_generation_identified(columns: TraceColumns) -> ast.Expr:
    """A generation from a PostHog SDK that names a user. Feedback and metric events carry real user ids even when the
    generations do not, so only a generation shows that the SDK identifies users."""
    return ast.And(
        exprs=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq, left=columns.event, right=ast.Constant(value="$ai_generation")
            ),
            event_identified(columns),
        ]
    )
