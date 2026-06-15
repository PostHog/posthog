from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_clickhouse_string


def matches_action(node: ast.Expr, args: list[ast.Expr], context: HogQLContext, events_alias: str) -> ast.Expr:
    arg = args[0]
    if not isinstance(arg, ast.Constant):
        raise QueryError("action() takes only constant arguments", node=arg)
    if context.team_id is None:
        raise QueryError("action() can only be used in a query with a team_id", node=arg)

    if (isinstance(arg.value, int) or isinstance(arg.value, float)) and not isinstance(arg.value, bool):
        matches = context.data.actions(int(arg.value), scope="project")
        if len(matches) != 1:
            raise QueryError(f"Could not find an action with the ID {arg.value}", node=arg)
        context.add_notice(
            start=arg.start,
            end=arg.end,
            message=f"Action #{matches[0].id} can also be specified as {escape_clickhouse_string(matches[0].name)}",
            fix=escape_clickhouse_string(matches[0].name),
        )
        expr = context.data.action_expr(matches[0].id, events_alias=events_alias)
        if expr is None:
            raise QueryError(f"Could not resolve action #{matches[0].id} to an expression", node=arg)
        return expr

    if isinstance(arg.value, str):
        matches = context.data.actions(arg.value, scope="project")
        if len(matches) > 1:
            raise QueryError(f"Found multiple actions with name '{arg.value}'", node=arg)
        if len(matches) != 1:
            raise QueryError(f"Could not find an action with the name '{arg.value}'", node=arg)
        context.add_notice(
            start=arg.start,
            end=arg.end,
            message=f"Searching for action by name. Replace with numeric ID {matches[0].id} to protect against renaming.",
            fix=str(matches[0].id),
        )
        expr = context.data.action_expr(matches[0].id, events_alias=events_alias)
        if expr is None:
            raise QueryError(f"Could not resolve action '{arg.value}' to an expression", node=arg)
        return expr

    raise QueryError("action() takes exactly one string or integer argument", node=arg)
