from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_expr, parse_statement
from posthog.hogql.printer import print_ast


def translate_hogql(query: str, context: HogQLContext) -> str:
    """Translate a HogQL expression into a Clickhouse expression."""
    if query == "":
        raise ValueError("Empty query")

    try:
        if context.select_team_id:
            node = parse_statement(query)
        else:
            node = parse_expr(query)
    except SyntaxError as err:
        raise ValueError(f"SyntaxError: {err.msg}")
    except NotImplementedError as err:
        raise ValueError(f"NotImplementedError: {err}")
    return print_ast(node, [], context, "clickhouse")
