from typing import Dict, Literal, cast, Optional

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.errors import (
    HogQLException,
    NotImplementedException,
    SyntaxException,
)
from posthog.hogql.parser import parse_expr
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.visitor import clone_expr


# This is called only from "non-hogql-based" insights to translate HogQL expressions into ClickHouse SQL
# All the constant string values will be collected into context.values
def translate_hogql(
    query: str,
    context: HogQLContext,
    dialect: Literal["hogql", "clickhouse"] = "clickhouse",
    metadata_source: Optional[ast.SelectQuery] = None,
    *,
    events_table_alias: Optional[str] = None,
    placeholders: Optional[Dict[str, ast.Expr]] = None,
) -> str:
    """Translate a HogQL expression into a ClickHouse expression."""
    if query == "":
        raise HogQLException("Empty query")

    try:
        # Create a fake query that selects from "events" to have fields to select from.
        if context.database is None:
            if context.team_id is None:
                raise ValueError("Cannot translate HogQL for a filter with no team specified")
            context.database = create_hogql_database(context.team_id)
        node = parse_expr(query, placeholders=placeholders)
        if metadata_source is not None:
            select_query = cast(ast.SelectQuery, clone_expr(metadata_source, clear_locations=True))
            select_query.select.append(node)
        else:
            select_query = ast.SelectQuery(select=[node], select_from=ast.JoinExpr(table=ast.Field(chain=["events"])))

        if events_table_alias is not None:
            select_query.select_from.alias = events_table_alias

        prepared_select_query: ast.SelectQuery = cast(
            ast.SelectQuery,
            prepare_ast_for_printing(select_query, context=context, dialect=dialect, stack=[select_query]),
        )
        return print_prepared_ast(
            prepared_select_query.select[0],
            context=context,
            dialect=dialect,
            stack=[prepared_select_query],
        )
    except (NotImplementedException, SyntaxException):
        raise
