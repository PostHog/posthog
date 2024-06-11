from typing import Any
from posthog.models.action.action import Action
from posthog.hogql.bytecode import create_bytecode
from posthog.hogql.parser import parse_expr, parse_string_template
from posthog.hogql.property import action_to_expr, property_to_expr, ast
from posthog.models.team.team import Team


def hog_function_filters_to_expr(filters: dict, team: Team, actions: dict[int, Action]) -> ast.Expr:
    test_account_filters_exprs: list[ast.Expr] = []
    if filters.get("filter_test_accounts", False):
        test_account_filters_exprs = [property_to_expr(property, team) for property in team.test_account_filters]

    all_filters = filters.get("events", []) + filters.get("actions", [])
    all_filters_exprs: list[ast.Expr] = []

    if not all_filters and test_account_filters_exprs:
        # Always return test filters if set and no other filters
        return ast.And(exprs=test_account_filters_exprs)

    for filter in all_filters:
        exprs: list[ast.Expr] = []
        exprs.extend(test_account_filters_exprs)

        # Events
        if filter.get("type") == "events" and filter.get("name"):
            exprs.append(parse_expr("event = {event}", {"event": ast.Constant(value=filter["name"])}))

        # Actions
        if filter.get("type") == "actions":
            try:
                action = actions[int(filter["id"])]
                exprs.append(action_to_expr(action))
            except KeyError:
                # If an action doesn't exist, we want to return no events
                exprs.append(parse_expr("1 = 2"))

        # Properties
        if filter.get("properties"):
            exprs.append(property_to_expr(filter.get("properties"), team))

        if len(exprs) == 0:
            all_filters_exprs.append(ast.Constant(value=True))

        all_filters_exprs.append(ast.And(exprs=exprs))

    if all_filters_exprs:
        final_expr = ast.Or(exprs=all_filters_exprs)
        return final_expr
    else:
        return ast.Constant(value=True)


def generate_template_bytecode(obj: Any) -> Any:
    """
    Clones an object, compiling any string values to bytecode templates
    """

    if isinstance(obj, dict):
        return {key: generate_template_bytecode(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [generate_template_bytecode(item) for item in obj]
    elif isinstance(obj, str):
        return create_bytecode(parse_string_template(obj))
    else:
        return obj
