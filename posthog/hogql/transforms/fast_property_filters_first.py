"""Put the fast property filters of a native JSON events read at the front of its WHERE.

A property of the native events table is one path of a JSON column. ClickHouse evaluates the conditions it moves to
PREWHERE in read steps, and a later step reads its columns only where the earlier steps kept rows. It orders the
steps by the stored size of the columns they read. It has a size for a path of a JSON column only when
``allow_calculating_subcolumns_sizes_for_merge_tree_reading`` is on, and that setting costs planning time on a table
with many parts. Without it, two filters on one JSON column tie, and a tie keeps the order of the query. A filter
that parses a whole property then runs before a filter that reads one small value, when the query wrote it first.

A fast filter compares one path of a native JSON column with constants. Its read is bare, or wrapped in conversions that
give NULL for a value they cannot convert, so the read cannot fail. Its comparison is positive, such as ``=``, ``<`` or
``IN``, or it tests for NULL. A positive comparison is true only for a row on which ClickHouse evaluated it. So one
with a constant that ClickHouse cannot compare with the read, such as ``properties.plan = 5`` on text, matches no row
wherever it runs, and the move can only make a query that returns nothing report the error. A negated comparison is
also true for a row without the property, where ClickHouse never evaluates it, so it keeps its written order. So does a
filter that can fail on some rows, such as ``properties.plan::int > 0``, and every other filter. A filter that guards a
later conversion therefore still runs before it. The position of a fast filter against filters on other columns
changes nothing, because ClickHouse orders those by column size.

Two more things keep their written order. A filter on an event's ``$feature_flags``, ``$active_feature_flags`` or
``$feature/<key>`` does, because the native table rebuilds each of them from the whole flag map, which is not a small
read. A whole WHERE does when a function such as ``rowNumberInBlock()`` can run in it. That function numbers the rows
that reach it, so a filter moved ahead of it changes which rows those are. A WHERE can call the function itself or
through an alias, and the check does not follow aliases. It keeps the written order when the SELECT list of the same
query calls the function, and in every WHERE of the query when a WITH alias calls it, because HogQL resolves a WITH
alias in every SELECT. A nested SELECT is checked on its own, so numbering the rows a subquery returns leaves the
filters inside it free to move.
"""

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.constants import is_virtual_feature_flag_key
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.util.where_clause_extractor import is_nondeterministic_function, top_level_conjuncts
from posthog.hogql.visitor import TraversingVisitor

_POSITIVE_COMPARISONS = frozenset(
    {
        ast.CompareOperationOp.Eq,
        ast.CompareOperationOp.Lt,
        ast.CompareOperationOp.LtEq,
        ast.CompareOperationOp.Gt,
        ast.CompareOperationOp.GtEq,
        ast.CompareOperationOp.In,
    }
)

# None of these fails on a value: HogQL prints the conversions so that a value they cannot convert becomes NULL. The
# property type pass wraps them around a typed property, and a Boolean one is `toBool(transform(toString(...), ...))`.
_CONVERSIONS = frozenset({"toFloat", "toDateTime", "toString", "toBool", "transform"})


def _property_read(expr: ast.Expr) -> ast.Expr:
    """`expr` without the aliases and the conversions around it.

    A conversion with an argument that is not a constant stays, because that argument can fail on a row.
    """
    while True:
        if isinstance(expr, ast.Alias):
            expr = expr.expr
        elif (
            isinstance(expr, ast.Call)
            and expr.name in _CONVERSIONS
            and expr.args
            and all(isinstance(arg, ast.Constant) for arg in expr.args[1:])
        ):
            expr = expr.args[0]
        else:
            return expr


def _is_not_null_test(term: ast.CompareOperation) -> bool:
    return term.op == ast.CompareOperationOp.NotEq and isinstance(term.right, ast.Constant) and term.right.value is None


def _is_constant(expr: ast.Expr) -> bool:
    if isinstance(expr, (ast.Tuple, ast.Array)):
        return all(isinstance(item, ast.Constant) for item in expr.exprs)
    return isinstance(expr, ast.Constant)


def _reads_a_json_column_path(property_read: ast.PropertyAccess, context: HogQLContext) -> bool:
    # Deferred: clickhouse_property_resolution imports the printer package, which imports this module.
    from posthog.hogql.transforms.clickhouse_property_resolution import (  # noqa: PLC0415
        _is_events_properties,
        resolve_materialized_property_source,
    )

    blob_type = property_read.expr.type
    if not isinstance(blob_type, ast.FieldType):
        return False
    key = str(property_read.keys[0])
    if is_virtual_feature_flag_key(key) and _is_events_properties(blob_type, context):
        return False
    source = resolve_materialized_property_source(blob_type, key, context)
    return source is not None and source.kind == "json_subcolumn"


def _is_fast_property_filter(term: ast.Expr, context: HogQLContext) -> bool:
    if not isinstance(term, ast.CompareOperation):
        return False
    if term.op not in _POSITIVE_COMPARISONS and not _is_not_null_test(term):
        return False
    property_read = _property_read(term.left)
    return (
        isinstance(property_read, ast.PropertyAccess)
        and len(property_read.keys) == 1
        and _is_constant(term.right)
        and _reads_a_json_column_path(property_read, context)
    )


class _OrderSensitiveCallFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_call(self, node: ast.Call) -> None:
        if is_nondeterministic_function(node.name):
            self.found = True
        super().visit_call(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # A nested SELECT numbers its own rows, whatever order the filters around it run in.
        pass


def _calls_an_order_sensitive_function(exprs: list[ast.Expr]) -> bool:
    finder = _OrderSensitiveCallFinder()
    for expr in exprs:
        finder.visit(expr)
    return finder.found


class _FastPropertyFiltersFirst(TraversingVisitor):
    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self.context = context
        self.reordered: list[tuple[ast.SelectQuery, ast.Expr]] = []
        self.with_alias_is_order_sensitive = False

    def visit_cte(self, node: ast.CTE) -> None:
        if _calls_an_order_sensitive_function([node.expr]):
            self.with_alias_is_order_sensitive = True
        super().visit_cte(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        super().visit_select_query(node)

        if node.where is None:
            return

        terms = top_level_conjuncts(node.where)
        is_fast = [_is_fast_property_filter(term, self.context) for term in terms]
        first_other = is_fast.index(False) if False in is_fast else len(terms)
        if True not in is_fast[first_other:] or _calls_an_order_sensitive_function([node.where, *node.select]):
            return

        reordered = ast.And(
            exprs=[term for term, fast in zip(terms, is_fast) if fast]
            + [term for term, fast in zip(terms, is_fast) if not fast]
        )
        self.reordered.append((node, reordered))


def put_fast_property_filters_first(node: _T_AST, context: HogQLContext) -> _T_AST:
    """Reorder every eligible WHERE in the tree. Mutates in place and returns the node."""
    visitor = _FastPropertyFiltersFirst(context)
    visitor.visit(node)
    if not visitor.with_alias_is_order_sensitive:
        for select_query, where in visitor.reordered:
            select_query.where = where
    return node
