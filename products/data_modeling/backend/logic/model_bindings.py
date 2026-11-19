from collections.abc import Mapping

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen
from posthog.models import Team

from products.data_modeling.backend.logic.incremental_filter import parse_model_query

DOES_NOT_RESOLVE = "Its query would not run after the rename."
READS_ANOTHER_TABLE = "After the rename, a name in its query would refer to a different table or CTE."


@frozen
class QueryBindings:
    """What a query reads, as the resolver binds it: each table reference and field in the text the user wrote,
    in order, and the names of the output columns."""

    references: tuple[str, ...]
    columns: tuple[str, ...]


def _describe(type: ast.Type | None, view_names: Mapping[str, str]) -> str:
    """The table a type is bound to. `view_names` maps a model's name to the one it is compared under."""
    if isinstance(type, ast.FieldType | ast.AsteriskType):
        name = type.name if isinstance(type, ast.FieldType) else "*"
        return f"{name} of {_describe(type.table_type, view_names)}"
    if isinstance(type, ast.PropertyType):
        return f"{'.'.join(map(str, type.chain))} of {_describe(type.field_type, view_names)}"
    if isinstance(type, ast.SelectViewType):
        return f"model {view_names.get(type.view_name, type.view_name)}"
    if isinstance(type, ast.CTETableType):
        return f"cte {type.name}"
    if isinstance(type, ast.TableAliasType):
        return f"{type.alias} as {_describe(type.table_type, view_names)}"
    if isinstance(type, ast.TableType | ast.LazyTableType):
        return f"table {type.table.to_printed_hogql()}"
    if isinstance(type, ast.SelectQueryAliasType):
        return f"subquery {type.alias}"
    if isinstance(type, ast.LazyJoinType):
        return f"{type.field} of {_describe(type.table_type, view_names)}"
    return type.__class__.__name__


class _BindingCollector(TraversingVisitor):
    def __init__(self, view_names: Mapping[str, str]) -> None:
        super().__init__()
        self.view_names = view_names
        self.references: list[str] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # A model's body is expanded in place. It is the same before and after, so only the dependent's own text counts.
        if node.view_name is None:
            super().visit_select_query(node)

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        self.references.append(_describe(node.type, self.view_names))
        super().visit_join_expr(node)

    def visit_field(self, node: ast.Field) -> None:
        self.references.append(_describe(node.type, self.view_names))


def query_bindings(
    team: Team, query: str, database: Database, view_names: Mapping[str, str] | None = None
) -> QueryBindings:
    """Raises BaseHogQLError when the query does not resolve against `database`. `view_names` maps a model's
    name to the one its bindings are reported under."""
    context = HogQLContext(team_id=team.pk, team=team, enable_select_queries=True)
    context.database = database
    resolved = resolve_types(parse_model_query(query), context, dialect="clickhouse")
    collector = _BindingCollector(view_names or {})
    collector.visit(resolved)
    first = resolved.type
    while isinstance(first, ast.SelectSetQueryType):
        first = first.types[0]
    columns = tuple(first.columns) if isinstance(first, ast.SelectQueryType) else ()
    return QueryBindings(references=tuple(collector.references), columns=columns)


def binding_change(
    team: Team, before: QueryBindings, after_query: str, renamed_database: Database, old_name: str, new_name: str
) -> str | None:
    """Why `after_query` against the renamed database does not read what the query read before, or None."""
    try:
        after = query_bindings(team, after_query, renamed_database, {new_name: old_name})
    except BaseHogQLError:
        return DOES_NOT_RESOLVE
    if after.references != before.references:
        return READS_ANOTHER_TABLE
    for old, new in zip(before.columns, after.columns):
        if old != new:
            return f"The rename would change its output column {old} to {new}. Give that column an alias first."
    if len(after.columns) != len(before.columns):
        return READS_ANOTHER_TABLE
    return None
