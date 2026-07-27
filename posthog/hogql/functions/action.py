from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_clickhouse_string

if TYPE_CHECKING:
    from products.actions.backend.models.action import Action


def _assert_can_read_action(action: "Action", context: HogQLContext, node: ast.Expr) -> None:
    """Apply access control to a directly referenced action.

    `matchesAction(<id>)` resolves an action from the ORM, so it needs the same check that guards
    `system.actions` — otherwise a member who can't read an action can still evaluate its steps
    against events and read its name off the notice below. A userless database (background query
    runs, shared links) carries no access control and denies nothing, matching the printer's
    `build_access_control_guard`.
    """
    user_access_control = context.database.user_access_control if context.database is not None else None
    if user_access_control is None:
        return
    if not user_access_control.check_access_level_for_object(action, required_level="viewer"):
        raise QueryError(f"You don't have access to action #{action.pk}", node=node)


def matches_action(node: ast.Expr, args: list[ast.Expr], context: HogQLContext, events_alias: str) -> ast.Expr:
    arg = args[0]
    if not isinstance(arg, ast.Constant):
        raise QueryError("action() takes only constant arguments", node=arg)
    if context.team_id is None:
        raise QueryError("action() can only be used in a query with a team_id", node=arg)

    from posthog.hogql.property import action_to_expr

    from products.actions.backend.models.action import Action

    if (isinstance(arg.value, int) or isinstance(arg.value, float)) and not isinstance(arg.value, bool):
        actions = Action.objects.filter(id=int(arg.value), team__project_id=context.project_id).all()
        if len(actions) == 1:
            _assert_can_read_action(actions[0], context, arg)
            context.add_notice(
                start=arg.start,
                end=arg.end,
                message=f"Action #{actions[0].pk} can also be specified as {escape_clickhouse_string(actions[0].name)}",
                fix=escape_clickhouse_string(actions[0].name),
            )
            return action_to_expr(actions[0], events_alias=events_alias)
        raise QueryError(f"Could not find an action with ID {arg.value}", node=arg)

    if isinstance(arg.value, str):
        actions = Action.objects.filter(name=arg.value, team__project_id=context.project_id).all()
        if len(actions) == 1:
            _assert_can_read_action(actions[0], context, arg)
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
