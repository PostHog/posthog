from typing import Optional
from posthog.hogql.visitor import TraversingVisitor
from posthog.models.action.action import Action
from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import action_to_expr, property_to_expr, ast
from posthog.models.team.team import Team


def hog_function_filters_to_expr(filters: dict, team: Team, actions: dict[int, Action]) -> ast.Expr:
    common_filters_expr: list[ast.Expr] = []
    if filters.get("filter_test_accounts", False):
        common_filters_expr = [property_to_expr(property, team) for property in team.test_account_filters]

    all_filters = filters.get("events", []) + filters.get("actions", [])
    all_filters_exprs: list[ast.Expr] = []

    # Properties
    if filters.get("properties"):
        for prop in filters["properties"]:
            common_filters_expr.append(property_to_expr(prop, team))

    if not all_filters and common_filters_expr:
        # Always return test filters if set and no other filters
        return ast.And(exprs=common_filters_expr)

    for filter in all_filters:
        exprs: list[ast.Expr] = []
        exprs.extend(common_filters_expr)

        # Events
        if filter.get("type") == "events" and filter.get("id"):
            event_name = filter["id"]

            if event_name is None:
                # all events
                exprs.append(ast.Constant(value=1))
            else:
                exprs.append(parse_expr("event = {event}", {"event": ast.Constant(value=event_name)}))

        # Actions
        if filter.get("type") == "actions":
            try:
                action_id = int(filter["id"])
                action = actions.get(action_id, None)
                if not action:
                    action = Action.objects.get(id=action_id, team__project_id=team.project_id)
                exprs.append(action_to_expr(action))
            except KeyError:
                exprs.append(parse_expr("1 = 2"))  # No events match

        # Properties
        if filter.get("properties"):
            exprs.append(property_to_expr(filter.get("properties"), team))

        if len(exprs) == 0:
            all_filters_exprs.append(ast.Constant(value=True))

        all_filters_exprs.append(ast.And(exprs=exprs))

    if all_filters_exprs:
        return ast.Or(exprs=all_filters_exprs)

    return ast.Constant(value=True)


def filter_action_ids(filters: Optional[dict]) -> list[int]:
    if not filters:
        return []
    try:
        return [int(action["id"]) for action in filters.get("actions", [])]
    except KeyError:
        return []


def compile_filters_expr(filters: Optional[dict], team: Team, actions: Optional[dict[int, Action]] = None) -> ast.Expr:
    filters = filters or {}

    if actions is None:
        # If not provided as an optimization we fetch all actions
        actions_list = (
            Action.objects.select_related("team")
            .filter(team__project_id=team.project_id)
            .filter(id__in=filter_action_ids(filters))
        )
        actions = {action.id: action for action in actions_list}

    return hog_function_filters_to_expr(filters, team, actions)


class SelectFinder(TraversingVisitor):
    found = False

    def visit_select_query(self, node):
        self.found = True
        return

    # class method
    @classmethod
    def has_select(cls, node):
        visitor = cls()
        visitor.visit(node)
        return visitor.found


def compile_filters_bytecode(filters: Optional[dict], team: Team, actions: Optional[dict[int, Action]] = None) -> dict:
    filters = filters or {}
    try:
        expr = compile_filters_expr(filters, team, actions)
        if SelectFinder.has_select(expr):
            raise Exception("Select queries are not allowed in filters")

        filters["bytecode"] = create_bytecode(expr).bytecode
        if "bytecode_error" in filters:
            del filters["bytecode_error"]
    except Exception as e:
        # TODO: Better reporting of this issue
        filters["bytecode"] = None
        filters["bytecode_error"] = str(e)

    return filters
