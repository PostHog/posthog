from typing import Optional

from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import action_to_expr, ast, property_to_expr
from posthog.hogql.visitor import TraversingVisitor

from posthog.models.action.action import Action
from posthog.models.team.team import Team


def hog_function_filters_to_expr(filters: dict, team: Team, actions: dict[int, Action]) -> ast.Expr:
    # Build test account filters that should exclude events
    test_account_filters: list[ast.Expr] = []
    if filters.get("filter_test_accounts", False):
        test_account_filters = [property_to_expr(property, team) for property in team.test_account_filters]

    # Build global property filters
    global_property_filters: list[ast.Expr] = []
    if filters.get("properties"):
        for prop in filters["properties"]:
            global_property_filters.append(property_to_expr(prop, team))

    all_filters = filters.get("events", []) + filters.get("actions", [])

    # If no event/action filters, just return the filters we have
    if not all_filters:
        combined_filters = test_account_filters + global_property_filters
        if combined_filters:
            return ast.And(exprs=combined_filters)
        return ast.Constant(value=True)

    # Build event/action filters
    event_action_exprs: list[ast.Expr] = []

    for filter in all_filters:
        exprs: list[ast.Expr] = []

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

        # Per-filter properties (if any)
        if filter.get("properties"):
            exprs.append(property_to_expr(filter.get("properties"), team))

        if len(exprs) == 0:
            event_action_exprs.append(ast.Constant(value=True))
        elif len(exprs) == 1:
            event_action_exprs.append(exprs[0])
        else:
            event_action_exprs.append(ast.And(exprs=exprs))

    # Combine event/action filters with OR
    combined_events_expr = ast.Or(exprs=event_action_exprs) if len(event_action_exprs) > 1 else event_action_exprs[0]

    # Now combine everything: test account filters, global properties, and events
    # Structure: (test_account_filter1 AND test_account_filter2 AND ...) AND global_properties AND (event1 OR event2 OR ...)
    final_exprs: list[ast.Expr] = []

    # Add test account filters (these exclude matching events)
    final_exprs.extend(test_account_filters)

    # Add global property filters
    final_exprs.extend(global_property_filters)

    # Add the event/action expression
    final_exprs.append(combined_events_expr)

    if len(final_exprs) == 1:
        return final_exprs[0]

    return ast.And(exprs=final_exprs)


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
