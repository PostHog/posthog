from posthog.schema import HogQLNotice

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import TraversingVisitor, clone_expr

# posthog/models/flag_evaluations/sql.py defines this name too. It imports django.conf, which this module keeps
# off its import path, so the name is spelled out here.
FLAG_CALLED_EVENT = "$feature_flag_called"

# Orgs that can't query posthog.flag_evaluations yet get this warning too, so the copy speaks of the move in the future.
FLAG_CALLED_ON_EVENTS_WARNING = (
    f"{FLAG_CALLED_EVENT} is moving from events to posthog.flag_evaluations. Once the move finishes "
    "for your organization, this query will stop returning these events and you can query "
    "posthog.flag_evaluations instead."
)


class _FlagCalledOnEventsFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.literals: list[ast.Constant] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # The resolver inlines a saved view's body, parsed from the view's own text. Its offsets do not
        # point into the user's query.
        if node.view_name is not None:
            return
        super().visit_select_query(node)

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        if node.op in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.In, ast.CompareOperationOp.GlobalIn):
            for field_side, value_side in ((node.left, node.right), (node.right, node.left)):
                if _is_events_event_field(field_side):
                    self.literals.extend(_flag_called_constants(value_side))
        super().visit_compare_operation(node)


def _is_events_event_field(expr: ast.Expr) -> bool:
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    if not isinstance(expr, ast.Field):
        return False
    # A select alias used in WHERE wraps the column in one FieldAliasType per alias.
    field_type = expr.type
    while isinstance(field_type, ast.FieldAliasType):
        field_type = field_type.type
    if not isinstance(field_type, ast.FieldType) or field_type.name != "event":
        return False
    table_type = field_type.table_type
    while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
        table_type = table_type.table_type
    return isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable)


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
    finder = _FlagCalledOnEventsFinder()
    with context.timings.measure("flag_called_warnings"):
        finder.visit(resolve_types(clone_expr(node), context, dialect="clickhouse"))
    # A literal that a variable supplies has no span, and a notice without one marks the whole query.
    return [
        HogQLNotice(message=FLAG_CALLED_ON_EVENTS_WARNING, start=literal.start, end=literal.end)
        for literal in finder.literals
        if literal.start is not None and literal.end is not None
    ]
