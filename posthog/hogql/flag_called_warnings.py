from posthog.schema import HogQLNotice

from posthog.hogql import ast
from posthog.hogql.constants import FLAG_CALLED_EVENT
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import Table
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.flag_evaluations import FlagEvaluationsTable
from posthog.hogql.database.schema.util.where_clause_extractor import event_field_type, unwrap_table_alias_type
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.dataclasses import frozen

# Orgs that can't query posthog.flag_evaluations yet get this warning too, so the copy speaks of the move in the future.
FLAG_CALLED_ON_EVENTS_WARNING = (
    f"{FLAG_CALLED_EVENT} is moving from events to posthog.flag_evaluations. Once the move finishes "
    "for your organization, this query will stop returning these events and you can query "
    "posthog.flag_evaluations instead."
)

FLAG_CALLED_FROM_FLAG_EVALUATIONS_NOTICE = (
    f"This query reads {FLAG_CALLED_EVENT} events from posthog.flag_evaluations, which keeps the last 90 days "
    "of flag calls."
)


class _FlagCalledLiteralFinder(TraversingVisitor):
    def __init__(self, table_class: type[Table]) -> None:
        super().__init__()
        self.table_class = table_class
        self.literals: list[ast.Constant] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # The resolver inlines a saved view's body, parsed from the view's own text. Its offsets do not
        # point into the user's query.
        if node.view_name is not None:
            return
        super().visit_select_query(node)

    def visit_alias(self, node: ast.Alias) -> None:
        # The resolver inlines a saved expression's body in a hidden alias. The body's offsets point into its own text.
        if node.hidden:
            return
        super().visit_alias(node)

    def visit_field(self, node: ast.Field) -> None:
        # The inherited visit follows the field's type into shared CTE types, which takes exponential time.
        pass

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        if node.op in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.In, ast.CompareOperationOp.GlobalIn):
            for field_side, value_side in ((node.left, node.right), (node.right, node.left)):
                if _is_event_field_of(field_side, self.table_class):
                    self.literals.extend(_flag_called_constants(value_side))
        super().visit_compare_operation(node)


def _is_event_field_of(expr: ast.Expr, table_class: type[Table]) -> bool:
    field_type = event_field_type(expr)
    if field_type is None:
        return False
    table_type = unwrap_table_alias_type(field_type.table_type)
    return isinstance(table_type, ast.TableType) and isinstance(table_type.table, table_class)


def _flag_called_constants(expr: ast.Expr) -> list[ast.Constant]:
    if isinstance(expr, ast.Constant):
        return [expr] if expr.value == FLAG_CALLED_EVENT else []
    if isinstance(expr, (ast.Tuple, ast.Array)):
        return [constant for sub in expr.exprs for constant in _flag_called_constants(sub)]
    return []


def flag_called_on_events_warnings(
    node: ast.SelectQuery | ast.SelectSetQuery, context: HogQLContext
) -> list[HogQLNotice]:
    """A warning on each `$feature_flag_called` literal that a query compares to the events table's `event` column.

    The query resolves on a clone, because the printed AST has been rewritten and its offsets no longer match
    what the user typed.
    """
    # A caller that passes an already printed AST never builds the database, and its AST may be rewritten.
    if context.database is None:
        return []
    finder = _FlagCalledLiteralFinder(EventsTable)
    with context.timings.measure("flag_called_warnings"):
        finder.visit(resolve_types(clone_expr(node), context, dialect="clickhouse"))
    # A literal that a variable supplies has no span, and a notice without one marks the whole query.
    return [
        HogQLNotice(message=FLAG_CALLED_ON_EVENTS_WARNING, start=literal.start, end=literal.end)
        for literal in finder.literals
        if literal.start is not None and literal.end is not None
    ]


@frozen
class LiteralSpan:
    start: int | None
    end: int | None


def flag_called_spans_read_from_flag_evaluations(prepared: ast.AST) -> set[LiteralSpan]:
    """The spans of the `$feature_flag_called` literals that a prepared AST compares to `flag_evaluations.event`."""
    finder = _FlagCalledLiteralFinder(FlagEvaluationsTable)
    finder.visit(prepared)
    return {LiteralSpan(start=literal.start, end=literal.end) for literal in finder.literals}
