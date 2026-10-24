"""Inject an incremental window filter into a saved query's AST.

The user picks an output column; we do the rest. Two filters go in, and they do different jobs:

1. A predicate on the key's **defining expression**, ANDed into the outermost ``WHERE``. Because
   ``WHERE`` runs before ``GROUP BY``, this prunes source rows, which is what makes an incremental
   run cheaper than a full one. Filtering on the expression rather than on a raw timestamp is also
   what guarantees a grouped bucket is recomputed whole: ``toStartOfDay(timestamp) >= <watermark>``
   pulls in every row of every touched day, not just the rows after the watermark instant.

2. An outer guard on the key's output column. It costs one pass over an already-narrowed result and
   guarantees no row outside the window reaches the table, even for a query shape where (1) lands
   somewhere the planner cannot fully honour.
"""

from collections.abc import Callable
from functools import partial
from typing import Any, Optional, Union

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import clone_expr

SelectLike = Union[ast.SelectQuery, ast.SelectSetQuery]
WindowPredicate = Callable[[ast.Expr], ast.Expr]

# The alias the outer guard binds the user's query to. Leading underscores keep it clear of
# anything a user would plausibly name a column.
GUARD_ALIAS = "__ph_incremental"


class IncrementalFilterError(ValueError):
    """The query cannot carry an incremental window filter.

    A user-input problem (a 400), not a server fault: the key column is missing, or it is produced
    by an aggregate and so cannot be filtered before grouping.
    """


def inject_incremental_filter(
    query: str,
    *,
    incremental_key: str,
    since: Any,
    until: Any = None,
    include_null_keys: bool = False,
) -> SelectLike:
    """Parse ``query`` and return it filtered to rows at or after ``since``."""
    return apply_incremental_filter(
        parse_select(query),
        incremental_key=incremental_key,
        since=since,
        until=until,
        include_null_keys=include_null_keys,
    )


def apply_incremental_filter(
    node: SelectLike,
    *,
    incremental_key: str,
    since: Any,
    until: Any = None,
    include_null_keys: bool = False,
) -> SelectLike:
    """Filter an already-parsed query, for callers that replace placeholders before filtering."""
    window = partial(_window_predicate, since=since, until=until, include_null_keys=include_null_keys)
    filtered = _push_predicate(node, incremental_key=incremental_key, window=window)
    return _wrap_with_guard(filtered, incremental_key=incremental_key, window=window)


def _window_predicate(key: ast.Expr, *, since: Any, until: Any, include_null_keys: bool) -> ast.Expr:
    bounded: ast.Expr = _compare(key, ast.CompareOperationOp.GtEq, since)
    if until is not None:
        bounded = ast.And(exprs=[bounded, _compare(key, ast.CompareOperationOp.Lt, until)])
    if not include_null_keys:
        return bounded
    return ast.Or(exprs=[bounded, ast.Call(name="isNull", args=[clone_expr(key)])])


def _compare(key: ast.Expr, op: ast.CompareOperationOp, value: Any) -> ast.CompareOperation:
    return ast.CompareOperation(left=clone_expr(key), right=ast.Constant(value=value), op=op)


def find_key_expression(select: ast.SelectQuery, incremental_key: str) -> Optional[ast.Expr]:
    """The expression behind an output column, or None when the query does not produce it.

    ``x AS key`` yields ``x``; a bare ``events.key`` yields the field itself.
    """
    for item in select.select:
        if isinstance(item, ast.Alias):
            if item.alias == incremental_key:
                return item.expr
        elif isinstance(item, ast.Field) and item.chain and str(item.chain[-1]) == incremental_key:
            return item
    # A star passes every source column through, the key included, so the key resolves by name
    # against the same sources. Without this, `SELECT *` plans incremental but the filter raises
    # on every run, and the activity's retry silently rebuilds the whole table each time. The
    # star's qualifier is kept (`e.*` filters on `e.key`): with a join in scope, a bare name can
    # be ambiguous and would fail the run at resolution.
    for item in select.select:
        if isinstance(item, ast.Field) and item.chain and str(item.chain[-1]) == "*":
            return ast.Field(chain=[*item.chain[:-1], incremental_key])
    return None


def _push_predicate(node: SelectLike, *, incremental_key: str, window: WindowPredicate) -> SelectLike:
    if isinstance(node, ast.SelectSetQuery):
        # Every branch of a union contributes rows to the same table, so every branch has to
        # produce the key and carry the filter, or the unfiltered branch rescans all of history.
        node.initial_select_query = _push_predicate(
            node.initial_select_query, incremental_key=incremental_key, window=window
        )
        for set_node in node.subsequent_select_queries:
            set_node.select_query = _push_predicate(
                set_node.select_query, incremental_key=incremental_key, window=window
            )
        return node

    key_expr = find_key_expression(node, incremental_key)
    if key_expr is None:
        raise IncrementalFilterError(f'Incremental key "{incremental_key}" is not one of this query\'s output columns.')

    node.where = _and(node.where, window(key_expr))
    return node


def _wrap_with_guard(node: SelectLike, *, incremental_key: str, window: WindowPredicate) -> ast.SelectQuery:
    return ast.SelectQuery(
        select=[ast.Field(chain=["*"])],
        select_from=ast.JoinExpr(table=node, alias=GUARD_ALIAS),
        where=window(ast.Field(chain=[GUARD_ALIAS, incremental_key])),
    )


def _and(existing: Optional[ast.Expr], predicate: ast.Expr) -> ast.Expr:
    if existing is None:
        return predicate
    # Flatten rather than nest, so a query filtered on several runs does not accumulate depth.
    if isinstance(existing, ast.And):
        return ast.And(exprs=[*existing.exprs, predicate])
    return ast.And(exprs=[existing, predicate])
