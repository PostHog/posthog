"""Add ``time_bucket`` bounds that match each ``timestamp`` bound on the ``metrics`` table.

``metrics`` reads ``metrics4_view``. Its ``metrics4_samples`` part stores the points of one series-hour in arrays,
and ``timestamp`` exists only after the ``ARRAY JOIN``. ClickHouse cannot use a ``timestamp`` filter to skip parts,
so a two-hour query reads all rows of the team. The sort key contains ``time_bucket``, the start of the UTC hour of
each point, so a ``time_bucket`` bound skips parts.

For a top-level ``AND`` term that compares ``metrics.timestamp`` with an expression without columns, the transform
adds a ``time_bucket`` term with the hour of the bound:

    timestamp >= x  or  timestamp > x   ->  time_bucket >= toStartOfHour(toTimeZone(x, 'UTC'))
    timestamp <= x  or  timestamp < x   ->  time_bucket <= toStartOfHour(toTimeZone(x, 'UTC'))

Each new term is true for every row that the ``timestamp`` term keeps, so no result changes. ``toTimeZone`` makes
sure that time zones with a half-hour offset round to the UTC hour.
"""

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.database.schema.metrics import MetricsTable
from posthog.hogql.visitor import TraversingVisitor, clone_expr

_LOWER_BOUND_OPS = (ast.CompareOperationOp.Gt, ast.CompareOperationOp.GtEq)
_UPPER_BOUND_OPS = (ast.CompareOperationOp.Lt, ast.CompareOperationOp.LtEq)
_FLIPPED_OPS = {
    ast.CompareOperationOp.Gt: ast.CompareOperationOp.Lt,
    ast.CompareOperationOp.GtEq: ast.CompareOperationOp.LtEq,
    ast.CompareOperationOp.Lt: ast.CompareOperationOp.Gt,
    ast.CompareOperationOp.LtEq: ast.CompareOperationOp.GtEq,
}


def add_metrics_time_bucket_bounds(node: _T_AST) -> _T_AST:
    """Add the bounds to every select in the tree. Mutates in place and returns the node."""
    _MetricsTimeBucketBoundsTransform().visit(node)
    return node


class _MetricsTimeBucketBoundsTransform(TraversingVisitor):
    def visit_select_query(self, node: ast.SelectQuery) -> None:
        super().visit_select_query(node)
        node.where = _with_bounds(node.where)
        node.prewhere = _with_bounds(node.prewhere)


def _with_bounds(where: ast.Expr | None) -> ast.Expr | None:
    if where is None:
        return None
    terms = _and_terms(where)
    bounds = [bound for term in terms if (bound := _time_bucket_bound(term)) is not None]
    bounds = [bound for bound in bounds if not any(_same_bound(bound, term) for term in terms)]
    if not bounds:
        return where
    return ast.And(exprs=[*terms, *bounds])


def _and_terms(expr: ast.Expr) -> list[ast.Expr]:
    if isinstance(expr, ast.And):
        return [term for sub in expr.exprs for term in _and_terms(sub)]
    return [expr]


def _time_bucket_bound(term: ast.Expr) -> ast.CompareOperation | None:
    if not isinstance(term, ast.CompareOperation) or term.op not in _FLIPPED_OPS:
        return None
    field, bound, op = _metrics_timestamp_field(term.left), term.right, term.op
    if field is None:
        field, bound, op = _metrics_timestamp_field(term.right), term.left, _FLIPPED_OPS[term.op]
    if field is None or _has_field(bound):
        return None

    assert isinstance(field.type, ast.FieldType)
    time_bucket = ast.Field(
        chain=[*field.chain[:-1], "time_bucket"],
        type=ast.FieldType(name="time_bucket", table_type=field.type.table_type),
    )
    hour = ast.Call(
        name="toStartOfHour",
        args=[ast.Call(name="toTimeZone", args=[clone_expr(bound, clear_types=False), ast.Constant(value="UTC")])],
    )
    new_op = ast.CompareOperationOp.GtEq if op in _LOWER_BOUND_OPS else ast.CompareOperationOp.LtEq
    return ast.CompareOperation(left=time_bucket, op=new_op, right=hour)


def _metrics_timestamp_field(expr: ast.Expr) -> ast.Field | None:
    # The property-type pass has already wrapped the column in toTimeZone.
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    if isinstance(expr, ast.Call) and expr.name == "toTimeZone" and expr.args:
        expr = expr.args[0]
        while isinstance(expr, ast.Alias):
            expr = expr.expr
    if not isinstance(expr, ast.Field) or not _is_metrics_field(expr.type, "timestamp"):
        return None
    return expr


def _is_metrics_field(type_: ast.Type | None, name: str) -> bool:
    # A computed select alias named `timestamp` resolves to its expression's type, not to the metrics FieldType.
    while isinstance(type_, ast.FieldAliasType):
        type_ = type_.type
    if not isinstance(type_, ast.FieldType) or type_.name != name:
        return False
    table_type = type_.table_type
    while isinstance(table_type, ast.TableAliasType):
        table_type = table_type.table_type
    return isinstance(table_type, ast.TableType) and isinstance(table_type.table, MetricsTable)


def _same_bound(bound: ast.CompareOperation, term: ast.Expr) -> bool:
    # Running the transform twice adds nothing: the second pass finds the terms of the first.
    return (
        isinstance(term, ast.CompareOperation)
        and term.op == bound.op
        and isinstance(term.left, ast.Field)
        and _is_metrics_field(term.left.type, "time_bucket")
        and clone_expr(term.right, clear_types=True, clear_locations=True)
        == clone_expr(bound.right, clear_types=True, clear_locations=True)
    )


class _FieldFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_field(self, node: ast.Field) -> None:
        self.found = True

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.found = True


def _has_field(expr: ast.Expr) -> bool:
    finder = _FieldFinder()
    finder.visit(expr)
    return finder.found
