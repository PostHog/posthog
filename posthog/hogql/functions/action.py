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

    from posthog.hogql.property import action_to_expr

    if (isinstance(arg.value, int) or isinstance(arg.value, float)) and not isinstance(arg.value, bool):
        if not context.data_bundle:
            raise QueryError("Action lookup requires data bundle in context", node=arg)
        
        action = context.data_bundle.get_action_by_id(int(arg.value))
        if action:
            context.add_notice(
                start=arg.start,
                end=arg.end,
                message=f"Action #{action.pk} can also be specified as {escape_clickhouse_string(action.name)}",
                fix=escape_clickhouse_string(action.name) if action.name else None,
            )
            return action_to_expr(action, events_alias=events_alias)
        raise QueryError(f"Could not find action with ID {arg.value}", node=arg)

    if isinstance(arg.value, str):
        if not context.data_bundle:
            raise QueryError("Action lookup requires data bundle in context", node=arg)
        
        action = context.data_bundle.get_action_by_name(arg.value)
        actions = [action] if action else []
        if len(actions) == 1:
            context.add_notice(
                start=arg.start,
                end=arg.end,
                message=f"Searching for action by name. Replace with numeric ID {actions[0].pk} to protect against renaming.",
                fix=str(actions[0].pk),
            )
            return action_to_expr(actions[0], events_alias=events_alias)
        elif len(actions) > 1:
            raise QueryError(f"Found multiple actions with name '{arg.value}'", node=arg)
        raise QueryError(f"Could not find an action with the name '{arg.value}'", node=arg)

    raise QueryError("action() takes exactly one string or integer argument", node=arg)
