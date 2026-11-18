"""Put the fast property filters of a native JSON events read at the front of its WHERE.

A property of the native events table is one path of a JSON column. ClickHouse evaluates the conditions it moves to
PREWHERE in read steps, and a later step reads its columns only where the earlier steps kept rows. It orders the
steps by the stored size of the columns they read. It has a size for a path of a JSON column only when
``allow_calculating_subcolumns_sizes_for_merge_tree_reading`` is on, and that setting costs planning time on a table
with many parts. Without it, two filters on one JSON column tie, and a tie keeps the order of the query. A filter
that parses a whole property then runs before a filter that reads one small value, when the query wrote it first.

A fast filter compares one path of a native JSON column with constants, and no part of it can fail to convert. The
read is text, or the conversion that the property type pass wraps around a Numeric or a Boolean property, which gives
NULL for a value that does not convert. Each constant already has the type of the read, or is decimal text that
ClickHouse parses into a number. Such a filter cannot raise on any row, so it is safe to run before a filter that the
query wrote first. A filter that converts can raise when it first runs on a row: ``properties.plan::int > 0`` on a
value that is not a number, or ``properties.plan = 5``, where ClickHouse finds no common type for text and a number.
That filter keeps its written order, and so does every other filter, so a filter that guards a later conversion still
runs before it. The position of a fast filter against filters on other columns changes nothing, because ClickHouse
orders those by column size.
"""

import re

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.util.where_clause_extractor import top_level_conjuncts
from posthog.hogql.visitor import TraversingVisitor

_COMPARISONS_WITH_CONSTANTS = frozenset(
    {
        ast.CompareOperationOp.Eq,
        ast.CompareOperationOp.NotEq,
        ast.CompareOperationOp.Lt,
        ast.CompareOperationOp.LtEq,
        ast.CompareOperationOp.Gt,
        ast.CompareOperationOp.GtEq,
        ast.CompareOperationOp.In,
        ast.CompareOperationOp.NotIn,
    }
)
_COMPARISONS_WITH_A_LIST = frozenset({ast.CompareOperationOp.In, ast.CompareOperationOp.NotIn})

_DECIMAL_TEXT = re.compile(r"-?\d+(\.\d+)?")


def _without_alias(expr: ast.Expr) -> ast.Expr:
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    return expr


def _typed_property_read(expr: ast.Expr) -> tuple[ast.PropertyAccess, type] | None:
    """The property read in `expr` with the Python type of its value, when the read cannot raise.

    A bare read is text. The other two shapes are the conversions that the property type pass wraps around a Numeric
    and a Boolean property, and both give NULL for a value that does not convert. Any other call or cast around a
    property does not match, because it can raise, or because one of its arguments can.
    """
    # The resolver wraps a field in a hidden alias: around the conversion of the type pass, and inside a call that the
    # query wrote.
    expr = _without_alias(expr)
    value_type: type = str
    match expr:
        case ast.Call(name="toFloat", args=[read]):
            expr, value_type = _without_alias(read), float
        case ast.Call(
            name="toBool",
            args=[
                ast.Call(
                    name="transform",
                    args=[
                        ast.Call(name="toString", args=[read]),
                        ast.Constant(value=["true", "false"]),
                        ast.Constant(value=[1, 0]),
                        ast.Constant(value=None),
                    ],
                )
            ],
        ):
            expr, value_type = _without_alias(read), bool
    return (expr, value_type) if isinstance(expr, ast.PropertyAccess) else None


def _is_constant_of_type(expr: ast.Expr, value_type: type) -> bool:
    if not isinstance(expr, ast.Constant):
        return False
    value = expr.value
    if value is None:
        return True
    if value_type is float:
        return isinstance(value, (int, float)) or (
            isinstance(value, str) and _DECIMAL_TEXT.fullmatch(value) is not None
        )
    return isinstance(value, value_type)


def _reads_a_json_column_path(property_read: ast.PropertyAccess, context: HogQLContext) -> bool:
    # Deferred: clickhouse_property_resolution imports the printer package, which imports this module.
    from posthog.hogql.transforms.clickhouse_property_resolution import (  # noqa: PLC0415
        resolve_materialized_property_source,
    )

    blob_type = property_read.expr.type
    if not isinstance(blob_type, ast.FieldType):
        return False
    source = resolve_materialized_property_source(blob_type, str(property_read.keys[0]), context)
    return source is not None and source.kind == "json_subcolumn"


def _is_fast_property_filter(term: ast.Expr, context: HogQLContext) -> bool:
    if not isinstance(term, ast.CompareOperation) or term.op not in _COMPARISONS_WITH_CONSTANTS:
        return False
    typed_read = _typed_property_read(term.left)
    if typed_read is None:
        return False
    property_read, value_type = typed_read
    compared = (
        term.right.exprs
        if term.op in _COMPARISONS_WITH_A_LIST and isinstance(term.right, (ast.Tuple, ast.Array))
        else [term.right]
    )
    return (
        len(property_read.keys) == 1
        and all(_is_constant_of_type(expr, value_type) for expr in compared)
        and _reads_a_json_column_path(property_read, context)
    )


class _FastPropertyFiltersFirst(TraversingVisitor):
    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self.context = context

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        super().visit_select_query(node)

        if node.where is None:
            return

        terms = top_level_conjuncts(node.where)
        is_fast = [_is_fast_property_filter(term, self.context) for term in terms]
        first_other = is_fast.index(False) if False in is_fast else len(terms)
        if True not in is_fast[first_other:]:
            return

        node.where = ast.And(
            exprs=[term for term, fast in zip(terms, is_fast) if fast]
            + [term for term, fast in zip(terms, is_fast) if not fast]
        )


def put_fast_property_filters_first(node: _T_AST, context: HogQLContext) -> _T_AST:
    """Reorder every eligible WHERE in the tree. Mutates in place and returns the node."""
    _FastPropertyFiltersFirst(context).visit(node)
    return node
