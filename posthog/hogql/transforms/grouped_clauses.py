"""The clause split of a grouped `SELECT`, for the passes that must not rewrite an expression after grouping."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from posthog.hogql import ast
from posthog.hogql.compilation import compilation_budget
from posthog.hogql.database.models import StringJSONDatabaseField
from posthog.hogql.functions.mapping import find_hogql_aggregation

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext

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


class GroupedJSONDocuments:
    def __init__(self, node: ast.SelectQuery, context: "HogQLContext") -> None:
        self.context = context
        self.fields: set[tuple[int, tuple[str, ...]]] = set()
        self._aliases = {expr.alias: expr.expr for expr in node.select if isinstance(expr, ast.Alias)}
        self._seen_aliases: set[str] = set()
        grouping_keys = node.select if node.group_by_mode == "all" else node.group_by or []
        for key in grouping_keys:
            for expr in key.exprs if isinstance(key, ast.GroupingSet) else [key]:
                if (
                    node.group_by_mode != "all"
                    and isinstance(expr, ast.Constant)
                    and isinstance(expr.value, int)
                    and not isinstance(expr.value, bool)
                    and 1 <= expr.value <= len(node.select)
                ):
                    expr = node.select[expr.value - 1]
                self._collect(expr)

    @staticmethod
    def _field_key(field_type: ast.FieldType) -> tuple[int, tuple[str, ...]]:
        table_type = field_type.table_type
        path = [field_type.name]
        # Virtual wrappers are recreated per reference; retain the FROM binding so self-joins stay distinct.
        while isinstance(table_type, ast.VirtualTableType):
            path.append(table_type.field)
            table_type = table_type.table_type
        return id(table_type), tuple(reversed(path))

    def contains(self, field_type: ast.FieldType) -> bool:
        return self._field_key(field_type) in self.fields

    def _collect(self, expr: ast.Expr) -> None:
        budget = compilation_budget.get()
        if budget is not None:
            budget.check_time()
        if isinstance(expr, ast.Alias):
            self._collect(expr.expr)
        elif isinstance(expr, ast.Tuple):
            for item in expr.exprs:
                self._collect(item)
        elif isinstance(expr, ast.Call):
            if expr.name == "tuple" or (expr.name == "toString" and len(expr.args) == 1):
                for item in expr.args:
                    self._collect(item)
        elif isinstance(expr, ast.Field):
            field_type = expr.type
            while isinstance(field_type, ast.FieldAliasType):
                field_type = field_type.type
            if isinstance(field_type, ast.FieldType) and isinstance(
                field_type.resolve_database_field(self.context), StringJSONDatabaseField
            ):
                self.fields.add(self._field_key(field_type))
            elif isinstance(expr.type, ast.FieldAliasType):
                alias = expr.type.alias
                if alias in self._aliases and alias not in self._seen_aliases:
                    self._seen_aliases.add(alias)
                    self._collect(self._aliases[alias])


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
