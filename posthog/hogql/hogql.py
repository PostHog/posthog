from typing import Literal

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database import database
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import print_ast


def translate_hogql(query: str, context: HogQLContext, dialect: Literal["hogql", "clickhouse"] = "clickhouse") -> str:
    """Translate a HogQL expression into a Clickhouse expression. Raises if any placeholders found."""
    if query == "":
        raise ValueError("Empty query")

    try:
        if context.select_team_id:
            # Only parse full SELECT statements if we have a team_id in the context.
            node = parse_select(query, no_placeholders=True)
            return print_ast(node, context, dialect, stack=[])
        else:
            # Create a fake query that selects from "events". Assume we are in its scope when evaluating expressions.
            select_query = ast.SelectQuery(
                select=[], symbol=ast.SelectQuerySymbol(tables={"events": ast.TableSymbol(table=database.events)})
            )
            node = parse_expr(query, no_placeholders=True)
            return print_ast(node, context, dialect, stack=[select_query])

    except SyntaxError as err:
        raise ValueError(f"SyntaxError: {err.msg}")
    except NotImplementedError as err:
        raise ValueError(f"NotImplementedError: {err}")
