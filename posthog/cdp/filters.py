from typing import Any, Optional

from django.conf import settings

from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import action_to_expr, ast, property_to_expr
from posthog.hogql.visitor import TraversingVisitor

from posthog.models.action.action import Action
from posthog.models.cohort.cohort import Cohort
from posthog.models.team.team import Team

COHORT_FILTER_TYPES = frozenset({"cohort", "static-cohort", "precalculated-cohort", "dynamic-cohort"})


class CohortInlineError(Exception):
    """Raised when cohort test account filters can't be inlined for real-time use."""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("Can't use cohorts in real-time filters")


def _is_cohort_filter(prop: dict) -> bool:
    return isinstance(prop, dict) and prop.get("type") in COHORT_FILTER_TYPES


def _check_only_person_properties(properties: Any) -> set[str]:
    """Walk a cohort's filter property tree and return any non-person leaf types found.

    Returns an empty set if all leaves are person property filters.
    """
    non_person_types: set[str] = set()

    def _walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                _walk(item)
            return
        if not isinstance(node, dict):
            return

        node_type = node.get("type")

        if node_type in ("AND", "OR"):
            values = node.get("values")
            if isinstance(values, list):
                for v in values:
                    _walk(v)
            return

        if node_type != "person":
            non_person_types.add(node_type or "<unknown>")

    _walk(properties)
    return non_person_types


def _try_inline_cohort_filter(prop: dict, team: Team) -> tuple[list[ast.Expr], None] | tuple[None, str]:
    """Try to inline a cohort test account filter as person property expressions.

    Returns (exprs, None) on success, or (None, reason) on failure.
    """
    cohort_id = prop.get("value")
    if cohort_id is None:
        return None, "cohort filter has no value"

    try:
        # nosemgrep: idor-lookup-without-team (scoped by team__project_id)
        cohort = Cohort.objects.get(id=cohort_id, team__project_id=team.project_id)
    except Cohort.DoesNotExist:
        return None, f"cohort id={cohort_id} not found"

    if cohort.is_static:
        return (
            None,
            f"cohort '{cohort.name}' (id={cohort_id}) is a static cohort — static cohort membership can't be evaluated in real-time filters",
        )

    cohort_properties = (cohort.filters or {}).get("properties")
    if not cohort_properties:
        return None, f"cohort '{cohort.name}' (id={cohort_id}) has no properties defined"

    non_person_types = _check_only_person_properties(cohort_properties)

    if non_person_types:
        types_str = ", ".join(sorted(non_person_types))
        return None, (
            f"cohort '{cohort.name}' (id={cohort_id}) contains {types_str} filters — "
            f"only cohorts with exclusively person property filters can be used in real-time filters"
        )

    # Reuse cohort_filters_to_expr which walks the same AND/OR tree structure.
    # Since _check_only_person_properties already validated only person leaves exist,
    # the behavioral/fallback branches in cohort_filters_to_expr are unreachable here.
    expr = cohort_filters_to_expr({"properties": cohort_properties}, team)
    # If the tree was empty/trivial, treat as if no properties
    if isinstance(expr, ast.Constant) and expr.value is True:
        return None, f"cohort '{cohort.name}' (id={cohort_id}) has no person property filters"

    is_negated = prop.get("negation") or prop.get("operator") == "not_in"
    if is_negated:
        result_expr: ast.Expr = ast.Not(expr=expr)
        return [result_expr], None

    return [expr], None


def _build_test_account_filters(filters: dict, team: Team) -> list[ast.Expr]:
    """Build filters to exclude test account events.

    For cohort filters that only contain person properties, inline the properties
    directly so they work in real-time bytecode filters (which can't do cohort lookups).
    """
    if not filters.get("filter_test_accounts", False):
        return []

    result: list[ast.Expr] = []
    inline_failures: list[str] = []
    for prop in team.test_account_filters:
        if _is_cohort_filter(prop):
            exprs, reason = _try_inline_cohort_filter(prop, team)
            if exprs is not None:
                result.extend(exprs)
                continue
            # Cohort couldn't be inlined — record the reason and skip the standard
            # path (property_to_expr would generate a CohortMembership node that
            # the bytecode compiler will reject anyway).
            if reason:
                inline_failures.append(reason)
            continue
        # Non-cohort filter — use standard path
        result.append(property_to_expr(prop, team))

    if inline_failures:
        raise CohortInlineError(inline_failures)

    return result


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
        # nosemgrep: idor-lookup-without-team (already scoped by team__project_id)
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


def _internal_user_settings_url(team_id: int) -> str:
    site_url = settings.SITE_URL.rstrip("/")
    return f"{site_url}/project/{team_id}/settings/project#internal-user-filtering"


def compile_filters_bytecode(filters: Optional[dict], team: Team, actions: Optional[dict[int, Action]] = None) -> dict:
    filters = filters or {}
    try:
        expr = compile_filters_expr(filters, team, actions)
        if SelectFinder.has_select(expr):
            raise Exception("Select queries are not allowed in filters")

        context = HogQLContext(team_id=team.id)
        filters["bytecode"] = create_bytecode(expr, context=context).bytecode

        # context.errors here only contains "function not implemented" errors from the
        # bytecode compiler (the resolver doesn't run during create_bytecode). These are
        # genuinely fatal — the bytecode would reference a non-existent function at runtime.
        if context.errors:
            error_messages = "; ".join(e.message for e in context.errors if e.message)
            raise Exception(f"Filter compilation errors: {error_messages}")
        if "bytecode_error" in filters:
            del filters["bytecode_error"]
    except CohortInlineError as e:
        settings_url = _internal_user_settings_url(team.id)
        details = "; ".join(e.reasons)
        filters["bytecode"] = None
        filters["bytecode_error"] = (
            f"Your internal/test user filters include cohorts that can't be used in real-time filters: "
            f"{details}. "
            f"Either switch to a cohort that only uses person properties, "
            f"or replace the cohort with inline person property filters. "
            f"Update your filters at: {settings_url}"
        )
    except Exception as e:
        error_msg = str(e)

        # Cohort errors from sources other than test account filters (e.g. global
        # property filters referencing a cohort) still hit the bytecode compiler's
        # generic "Can't use cohorts in real-time filters" error.
        if "Can't use cohorts in real-time filters" in error_msg:
            settings_url = _internal_user_settings_url(team.id)
            error_msg = (
                f"Cohort membership can't be evaluated in real-time filters. "
                f"Replace cohorts with equivalent inline person property filters. "
                f"Update your filters at: {settings_url}"
            )

        filters["bytecode"] = None
        filters["bytecode_error"] = error_msg

    return filters


# Realtime Cohort helpers


def build_behavioral_event_expr(behavioral_filter: dict, team: Team) -> ast.Expr | None:
    """Build combined expression for a behavioral event filter (event AND its per-filter properties).

    Supports only performed_event and performed_event_multiple (non-temporal bytecode use-case).
    Returns None for unsupported behavioral filters.
    """
    value = behavioral_filter.get("value")
    if value not in {"performed_event", "performed_event_multiple"}:
        # Unsupported behavioral types do not contribute to realtime bytecode
        return None

    event_name = behavioral_filter.get("key")
    if not isinstance(event_name, str) or not event_name:
        return None

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

    def _node_to_expr(node: Any) -> ast.Expr:
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
            expr = build_behavioral_event_expr(node, team)
            # Return True for unsupported behavioral filters
            return expr if expr is not None else ast.Constant(value=True)

        # Fallback to standard property handling (event/person/group/etc.)
        return property_to_expr(node, team)

    props = filters.get("properties")
    if not props:
        return ast.Constant(value=True)
    return _node_to_expr(props)
