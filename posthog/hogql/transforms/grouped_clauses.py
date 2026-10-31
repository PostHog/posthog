"""The clause split of a grouped `SELECT`, for the passes that must not rewrite an expression after grouping."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any

from posthog.hogql import ast
from posthog.hogql.functions.mapping import find_hogql_aggregation

# The clauses that see the grouped rows. FROM, WHERE, PREWHERE and ARRAY JOIN see the source rows.
GROUPED_CLAUSES = ("select", "group_by", "having", "order_by", "qualify", "window_exprs", "limit_by", "interpolate")


def is_grouped(node: ast.SelectQuery) -> bool:
    return bool(node.group_by) or node.group_by_mode == "all"


def before_grouping(node: ast.SelectQuery) -> ast.SelectQuery:
    """A copy of the query with only the clauses that see the source rows."""
    empty: dict[str, Any] = {clause: [] if clause == "select" else None for clause in GROUPED_CLAUSES}
    return replace(node, **empty)


def visit_after_grouping(node: ast.SelectQuery, visit: Callable[[Any], Any]) -> dict[str, Any]:
    """Visits each expression of the clauses that see the grouped rows, and returns the clauses rebuilt from the results."""
    rebuilt: dict[str, Any] = {}
    for clause in GROUPED_CLAUSES:
        value = getattr(node, clause)
        if isinstance(value, list):
            rebuilt[clause] = [visit(expr) for expr in value]
        elif isinstance(value, dict):
            rebuilt[clause] = {name: visit(expr) for name, expr in value.items()}
        else:
            rebuilt[clause] = visit(value) if value is not None else None
    return rebuilt


class GroupedClauseTracker:
    """Tracks whether the expression under visit sees the grouped rows.

    An expression in a grouped clause has to stay a function of the group keys, so a pass with this tracker skips the
    rewrites that would read a source column there. An aggregate's arguments see the source rows whatever clause the
    aggregate is in, and a nested query starts its own split.
    """

    _in_grouped_clause: bool = False

    @contextmanager
    def _grouped_clause(self, in_grouped_clause: bool) -> Iterator[None]:
        was_in_grouped_clause = self._in_grouped_clause
        self._in_grouped_clause = in_grouped_clause
        try:
            yield
        finally:
            self._in_grouped_clause = was_in_grouped_clause

    @contextmanager
    def _call_arguments(self, node: ast.Call) -> Iterator[None]:
        """The context of a call's arguments, which see the source rows when the call is an aggregate."""
        if self._in_grouped_clause and find_hogql_aggregation(node.name):
            with self._grouped_clause(False):
                yield
        else:
            yield
