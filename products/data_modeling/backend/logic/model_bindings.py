from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import SavedQuery
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.errors import BaseHogQLError, CompilationBudgetExceededError
from posthog.hogql.printer import print_prepared_ast
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen
from posthog.models import Team

from products.data_modeling.backend.logic.incremental_filter import parse_model_query

DOES_NOT_RESOLVE = "Its query would not run after the rename."
READS_ANOTHER_TABLE = "After the rename, a name in its query would refer to a different table or CTE."
DOES_NOT_RUN = "Its query does not run, so the rename cannot be checked against it."


# A structural reference: what a join reads, or what a field is bound to, with no name the rename changes.
Reference = tuple[object, ...]


@frozen
class QueryBindings:
    """What a query reads, as the resolver binds it: each join source and field in the text the user wrote,
    in order, and the name of each output column."""

    references: tuple[Reference, ...]
    columns: tuple[str, ...]


def _view_name(table: ast.Expr | None) -> str | None:
    """The model a join's subquery was expanded from. The resolver marks each branch of a model's body."""
    while isinstance(table, ast.SelectSetQuery):
        table = table.initial_select_query
    return table.view_name if isinstance(table, ast.SelectQuery) else None


class _BindingCollector(TraversingVisitor):
    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        self.joins: list[Reference] = []
        self.fields: list[ast.Type | None] = []
        # A field names its table through the scope type its join put in scope. Keyed by object, so two joins of
        # the same table stay apart, and mapped to the join's place in the text, so aliases never take part.
        self.join_of: dict[int, int] = {}

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # A model's body is expanded in place. It is the same before and after, so only the dependent's own text counts.
        if node.view_name is None:
            super().visit_select_query(node)

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        ordinal = len(self.joins)
        self.joins.append(self._source(node))
        if node.type is not None:
            self.join_of[id(node.type)] = ordinal
        super().visit_join_expr(node)

    def visit_field(self, node: ast.Field) -> None:
        self.fields.append(node.type)

    def _source(self, node: ast.JoinExpr) -> Reference:
        view_name = _view_name(node.table)
        if view_name is None:
            return self._table(node.type)
        # By the model's stored name, not a lookup: a synced table can own the bare name.
        model_node = self.database.authored_model_node(view_name)
        model = model_node.table if model_node is not None else self.database.get_table(view_name)
        return ("model", model.id if isinstance(model, SavedQuery) else view_name)

    def _table(self, type: ast.Type | None) -> Reference:
        if isinstance(type, ast.TableAliasType | ast.ColumnAliasedTableType):
            return self._table(type.table_type)
        if isinstance(type, ast.TableType | ast.LazyTableType):
            # A materialized model reads its backing table, which belongs to the model, not to its name.
            if isinstance(type.table, S3Table) and type.table.saved_query_id is not None:
                return ("model", type.table.saved_query_id)
            return ("table", type.table.to_printed_hogql())
        if isinstance(type, ast.CTETableAliasType):
            return self._table(type.cte_table_type)
        if isinstance(type, ast.CTETableType):
            return ("cte", type.name)
        if isinstance(type, ast.SelectQueryAliasType | ast.SelectQueryType | ast.SelectSetQueryType):
            return ("subquery",)
        return (type.__class__.__name__,)

    def _owner(self, type: ast.Type | None) -> Reference:
        if type is not None and id(type) in self.join_of:
            return ("join", self.join_of[id(type)])
        if isinstance(type, ast.LazyJoinType):
            return self.describe(type)
        # Not put in scope by a join of this text, such as a CTE read inside a model's body.
        return ("unscoped", *self._table(type))

    def describe(self, type: ast.Type | None) -> Reference:
        if isinstance(type, ast.FieldType):
            return ("field", type.name, self._owner(type.table_type))
        if isinstance(type, ast.AsteriskType):
            return ("*", self._owner(type.table_type))
        if isinstance(type, ast.PropertyType):
            return ("property", tuple(type.chain), self.describe(type.field_type))
        if isinstance(type, ast.LazyJoinType):
            return ("lazy join", type.field, self._owner(type.table_type))
        if isinstance(type, ast.FieldAliasType):
            return ("alias", type.alias, self.describe(type.type))
        # A table name in FROM is itself a field; its join's entry already records what it reads.
        return ("name of", self._owner(type))


def query_bindings(team: Team, query: str, database: Database) -> QueryBindings:
    """Raises BaseHogQLError when the query does not resolve against `database`."""
    context = HogQLContext(team_id=team.pk, team=team, enable_select_queries=True)
    context.database = database
    resolved = resolve_types(parse_model_query(query), context, dialect="clickhouse")
    collector = _BindingCollector(database)
    collector.visit(resolved)
    references = (*collector.joins, *(collector.describe(type) for type in collector.fields))
    first = resolved
    while isinstance(first, ast.SelectSetQuery):
        first = first.initial_select_query
    columns = (
        tuple(_output_name(column, context) for column in first.select) if isinstance(first, ast.SelectQuery) else ()
    )
    return QueryBindings(references=references, columns=columns)


def _output_name(column: ast.Expr, context: HogQLContext) -> str:
    # An unaliased expression is named after its text, so renaming a table it reads renames the column. The
    # resolver leaves some of these, such as arithmetic, out of a query's columns.
    if isinstance(column, ast.Alias):
        return column.alias
    if isinstance(column.type, ast.FieldAliasType):
        return column.type.alias
    if isinstance(column.type, ast.FieldType | ast.ExpressionFieldType):
        return column.type.name
    return print_prepared_ast(node=column, context=context, dialect="hogql")


def binding_change(team: Team, before: QueryBindings, after_query: str, renamed_database: Database) -> str | None:
    """Why `after_query` against the renamed database does not read what the query read before, or None."""
    try:
        after = query_bindings(team, after_query, renamed_database)
    except CompilationBudgetExceededError:
        raise
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
