"""Put the fast property filters of a native JSON events read at the front of its WHERE.

A property of the native events table is one path of a JSON column. ClickHouse evaluates the conditions it moves to
PREWHERE in read steps, and a later step reads its columns only where the earlier steps kept rows. It orders the
steps by the stored size of the columns they read. It has a size for a path of a JSON column only when
``allow_calculating_subcolumns_sizes_for_merge_tree_reading`` is on, and that setting costs planning time on a table
with many parts. Without it, two filters on one JSON column tie, and a tie keeps the order of the query. A filter
that parses a whole property then runs before a filter that reads one small value, when the query wrote it first.

A fast filter compares one property with constants. It cannot throw on a row that a filter written before it would
have rejected, so it is safe to move. Every other filter keeps its written order, so a filter that guards a later
conversion still runs before it. The position of a fast filter against filters on other columns changes nothing,
because ClickHouse orders those by column size.
"""

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.database.schema.util.where_clause_extractor import top_level_conjuncts
from posthog.hogql.property_planner import strip_property_conversions
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


def _is_constant_operand(expr: ast.Expr) -> bool:
    if isinstance(expr, (ast.Tuple, ast.Array)):
        return all(isinstance(item, ast.Constant) for item in expr.exprs)
    return isinstance(expr, ast.Constant)


def _is_fast_property_filter(term: ast.Expr) -> bool:
    if not isinstance(term, ast.CompareOperation) or term.op not in _COMPARISONS_WITH_CONSTANTS:
        return False
    for operand, other in ((term.left, term.right), (term.right, term.left)):
        property_read = strip_property_conversions(operand)
        if isinstance(property_read, ast.PropertyAccess) and len(property_read.keys) == 1:
            return _is_constant_operand(other)
    return False


class _FastPropertyFiltersFirst(TraversingVisitor):
    def visit_select_query(self, node: ast.SelectQuery) -> None:
        super().visit_select_query(node)

        if node.where is None:
            return

        terms = top_level_conjuncts(node.where)
        is_fast = [_is_fast_property_filter(term) for term in terms]
        first_other = is_fast.index(False) if False in is_fast else len(terms)
        if True not in is_fast[first_other:]:
            return

        node.where = ast.And(
            exprs=[term for term, fast in zip(terms, is_fast) if fast]
            + [term for term, fast in zip(terms, is_fast) if not fast]
        )


def put_fast_property_filters_first(node: _T_AST) -> _T_AST:
    """Reorder every eligible WHERE in the tree. Mutates in place and returns the node."""
    _FastPropertyFiltersFirst().visit(node)
    return node
