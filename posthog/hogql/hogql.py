from typing import Literal, cast

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.errors import HogQLException, NotImplementedException, SyntaxException
from posthog.hogql.parser import parse_expr
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast


# This is called only from "non-hogql-based" insights to translate HogQL expressions into ClickHouse SQL
# All the constant string values will be collected into context.values
def translate_hogql(query: str, context: HogQLContext, dialect: Literal["hogql", "clickhouse"] = "clickhouse") -> str:
    """Translate a HogQL expression into a Clickhouse expression. Raises if any placeholders found."""
    if query == "":
        raise HogQLException("Empty query")

    try:
        # Create a fake query that selects from "events" to have fields to select from.
        context.database = context.database or create_hogql_database(context.team_id)
        select_query_type = ast.SelectQueryType(tables={"events": ast.TableType(table=context.database.events)})
        node = parse_expr(query, no_placeholders=True)
        select_query = ast.SelectQuery(
            select=[node], select_from=ast.JoinExpr(table=ast.Field(chain=["events"])), type=select_query_type
        )
        prepared_ast: ast.SelectQuery = cast(
            ast.SelectQuery,
            prepare_ast_for_printing(select_query, context=context, dialect=dialect, stack=[select_query]),
        )
        return print_prepared_ast(prepared_ast.select[0], context=context, dialect=dialect, stack=[select_query])
    except (NotImplementedException, SyntaxException):
        raise
