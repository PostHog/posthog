from typing import Optional

from django.conf import settings

from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import action_to_expr, ast, property_to_expr
from posthog.hogql.visitor import TraversingVisitor

from posthog.models.action.action import Action
from posthog.models.team.team import Team


def _build_test_account_filters(filters: dict, team: Team) -> list[ast.Expr]:
    """Build filters to exclude test account events."""
    if not filters.get("filter_test_accounts", False):
        return []
    return [property_to_expr(property, team) for property in team.test_account_filters]


def _build_global_property_filters(filters: dict, team: Team) -> list[ast.Expr]:
    """Build global property filters that apply to all events."""
    if not filters.get("properties"):
        return []
    return [property_to_expr(prop, team) for prop in filters["properties"]]


def _build_event_filter_expr(filter: dict) -> ast.Expr:
    """Build expression for a single event filter."""
    event_name = filter.get("id")
    if event_name is None:
        return ast.Constant(value=True)  # Match all events
    return parse_expr("event = {event}", {"event": ast.Constant(value=event_name)})


def _build_action_filter_expr(filter: dict, actions: dict[int, Action], team: Team) -> ast.Expr:
    """Build expression for a single action filter."""
    try:
        action_id = int(filter["id"])
        action = actions.get(action_id)
        if not action:
            action = Action.objects.get(id=action_id, team__project_id=team.project_id)
        return action_to_expr(action)
    except KeyError:
        return parse_expr("1 = 2")  # No events match


def _build_single_filter_expr(filter: dict, actions: dict[int, Action], team: Team) -> ast.Expr:
    """Build expression for a single event or action filter with its properties."""
    filter_exprs: list[ast.Expr] = []

    # Add event or action expression
    if filter.get("type") == "events":
        filter_exprs.append(_build_event_filter_expr(filter))
    elif filter.get("type") == "actions":
        filter_exprs.append(_build_action_filter_expr(filter, actions, team))

    # Add per-filter properties
    filter_properties = filter.get("properties")
    if filter_properties:
        filter_exprs.append(property_to_expr(filter_properties, team))

    # Return single expression or AND combination
    if not filter_exprs:
        return ast.Constant(value=True)
    elif len(filter_exprs) == 1:
        return filter_exprs[0]
    else:
        return ast.And(exprs=filter_exprs)


def _combine_expressions(expressions: list[ast.Expr]) -> ast.Expr:
    """Combine a list of expressions into a single expression."""
    if not expressions:
        return ast.Constant(value=True)
    elif len(expressions) == 1:
        return expressions[0]
    else:
        return ast.And(exprs=expressions)


def hog_function_filters_to_expr(filters: dict, team: Team, actions: dict[int, Action]) -> ast.Expr:
    """
    Build a HogQL expression from hog function filters.

    Optimized to evaluate test account filters only once at the top level,
    rather than duplicating them for each event/action check.
    """
    # Build component filters
    test_account_filters = _build_test_account_filters(filters, team)
    global_property_filters = _build_global_property_filters(filters, team)

    # Get all event and action filters
    all_filters = filters.get("events", []) + filters.get("actions", [])

    # If no event/action filters, return just the account and property filters
    if not all_filters:
        return _combine_expressions(test_account_filters + global_property_filters)

    # Build expressions for each event/action filter
    event_action_exprs = [_build_single_filter_expr(filter, actions, team) for filter in all_filters]

    # Combine event/action filters with OR (match any of these events/actions)
    combined_events_expr = ast.Or(exprs=event_action_exprs) if len(event_action_exprs) > 1 else event_action_exprs[0]

    # Combine everything: test account filters AND global properties AND (events OR actions)
    # This structure ensures test account filters are evaluated only once
    final_exprs = test_account_filters + global_property_filters + [combined_events_expr]
    return _combine_expressions(final_exprs)


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
        error_msg = str(e)

        # Check if the error is about cohorts and if test account filters are involved
        if "Can't use cohorts in real-time filters" in error_msg and filters.get("filter_test_accounts", False):
            # Check if team has cohort filters in test account filters
            if team.test_account_filters:
                cohort_filters = [
                    f
                    for f in team.test_account_filters
                    if isinstance(f, dict)
                    and f.get("type") in ["cohort", "static-cohort", "precalculated-cohort", "dynamic-cohort"]
                ]
                if cohort_filters:
                    # Extract cohort information for the error message
                    cohort_info = []
                    for cohort_filter in cohort_filters:
                        value = cohort_filter.get("value")
                        if value:
                            cohort_info.append(f"cohort id={value}")

                    cohort_names = " (" + ", ".join(cohort_info) + ")" if cohort_info else ""
                    site_url = settings.SITE_URL.rstrip("/")
                    error_msg = (
                        f"Can't use cohorts in real-time filters. "
                        f"Update your filters at: {site_url}/project/{team.id}/settings/project#internal-user-filtering. "
                        f"Please inline the relevant expressions{cohort_names}."
                    )

        filters["bytecode"] = None
        filters["bytecode_error"] = error_msg

    return filters


# ========= Realtime Cohort helpers ========= #


def build_behavioral_event_expr(behavioral_filter: dict, team: Team) -> ast.Expr:
    """Build combined expression for a behavioral event filter (event AND its per-filter properties).

    Supports only performed_event and performed_event_multiple (non-temporal bytecode use-case).
    """
    value = behavioral_filter.get("value")
    if value not in {"performed_event", "performed_event_multiple"}:
        # Unsupported behavioral types do not contribute to realtime bytecode
        return ast.Constant(value=True)

    event_name = behavioral_filter.get("key")
    if not isinstance(event_name, str) or not event_name:
        return ast.Constant(value=True)

    parts: list[ast.Expr] = [parse_expr("event = {event}", {"event": ast.Constant(value=event_name)})]
    # Optional per-filter event properties
    event_filters = behavioral_filter.get("event_filters") or []
    if isinstance(event_filters, list) and event_filters:
        parts.append(property_to_expr(event_filters, team))

    return _combine_expressions(parts)


def cohort_filters_to_expr(filters: dict, team: Team) -> ast.Expr:
    """Assemble a HogQL expression for cohort filters similarly to hog function filters.

    - Recursively walks the cohort `properties` group
    - For behavioral filters, builds event matcher AND per-filter properties
    - For other filters, defers to property_to_expr
    """

    def _node_to_expr(node: any) -> ast.Expr:
        if isinstance(node, list):
            return _combine_expressions([_node_to_expr(child) for child in node])
        if not isinstance(node, dict):
            return ast.Constant(value=True)

        node_type = node.get("type")
        # PropertyGroup: {"type": "AND"|"OR", "values": [...]}
        if node_type in ("AND", "OR") and isinstance(node.get("values"), list):
            exprs = [_node_to_expr(child) for child in node["values"]]
            if node_type == "AND":
                return ast.And(exprs=exprs)
            else:
                return ast.Or(exprs=exprs)

        if node_type == "behavioral":
            return build_behavioral_event_expr(node, team)

        # Fallback to standard property handling (event/person/group/etc.)
        return property_to_expr(node, team)

    props = filters.get("properties")
    if not props:
        return ast.Constant(value=True)
    return _node_to_expr(props)
