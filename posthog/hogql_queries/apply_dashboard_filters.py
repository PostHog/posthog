from typing import Any

from posthog.schema import DashboardFilter, HogQLVariable, NodeKind

from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team

WRAPPER_NODE_KINDS = [NodeKind.DATA_TABLE_NODE, NodeKind.DATA_VISUALIZATION_NODE, NodeKind.INSIGHT_VIZ_NODE]

# Fields where a tile override replaces the dashboard value outright when set.
# Property filters are handled separately (AND-combined, not replaced).
_TILE_SCALAR_OVERRIDE_FIELDS = ["breakdown_filter", "interval", "filterTestAccounts"]


def merge_dashboard_and_tile_filters(dashboard_filters: dict | None, tile_filters: dict | None) -> dict | None:
    """Merge a tile's filter overrides on top of the dashboard-level filters.

    The tile wins per field, but the dashboard value is kept where the tile leaves a field unset,
    and property filters from both layers are AND-combined rather than replaced — a tile narrows the
    dashboard's filters instead of discarding them. The date range is treated as one unit: a tile that
    sets either bound supplies both bounds (and explicitDate), so a tile date_from is never paired with
    a stale dashboard date_to.
    """
    dashboard_filters = dashboard_filters or {}
    tile_filters = tile_filters or {}

    if not tile_filters:
        return dashboard_filters or None
    if not dashboard_filters:
        return tile_filters or None

    merged = {**dashboard_filters}

    for field in _TILE_SCALAR_OVERRIDE_FIELDS:
        if tile_filters.get(field) is not None:
            merged[field] = tile_filters[field]

    if tile_filters.get("date_from") is not None or tile_filters.get("date_to") is not None:
        merged["date_from"] = tile_filters.get("date_from")
        merged["date_to"] = tile_filters.get("date_to")
        if tile_filters.get("explicitDate") is not None:
            merged["explicitDate"] = tile_filters["explicitDate"]

    combined_properties = [*(dashboard_filters.get("properties") or []), *(tile_filters.get("properties") or [])]
    if combined_properties:
        merged["properties"] = combined_properties

    return merged


# Apply the filters from the django-style Dashboard object
def apply_dashboard_filters_to_dict(query: dict, filters: dict, team: Team) -> dict:
    if not filters:
        return query

    if query.get("kind") in WRAPPER_NODE_KINDS:
        source = apply_dashboard_filters_to_dict(query["source"], filters, team)
        return {**query, "source": source}

    try:
        query_runner = get_query_runner(query, team)
    except ValueError:
        capture_exception()
        return query
    query_runner.apply_dashboard_filters(DashboardFilter(**filters))
    return query_runner.query.model_dump()


# Apply the variables from the django-style Dashboard object
def apply_dashboard_variables_to_dict(query: dict, variables_overrides: dict[str, dict], team: Team) -> dict:
    if not variables_overrides:
        return query

    if query.get("kind") in WRAPPER_NODE_KINDS:
        source = apply_dashboard_variables_to_dict(query["source"], variables_overrides, team)
        return {**query, "source": source}

    if query.get("kind") == NodeKind.HOG_QL_QUERY:
        query_variables: dict[str, dict] | None = query.get("variables")
        if query_variables is None:
            return query

        for variable_id, overriden_hogql_variable in variables_overrides.items():
            query_variable = query_variables.get(variable_id)
            if query_variable:
                query_variables[variable_id] = {
                    "variableId": variable_id,
                    "code_name": query_variable["code_name"],
                    "value": overriden_hogql_variable.get("value"),
                }

        return {**query, "variables": query_variables}

    return query


def apply_dashboard_filters(query: Any, filters: DashboardFilter, team: Team) -> Any:
    """Apply dashboard filters directly to Pydantic models instead of dicts"""
    if not filters:
        return query

    if getattr(query, "kind", None) in WRAPPER_NODE_KINDS:
        source = apply_dashboard_filters(query.source, filters, team)
        return query.model_copy(update={"source": source})

    try:
        query_runner = get_query_runner(query, team)
    except ValueError:
        capture_exception()
        return query

    query_runner.apply_dashboard_filters(filters)
    return query_runner.query


def apply_dashboard_variables(query: Any, variables_overrides: dict[str, dict], team: Team) -> Any:
    """Apply dashboard variables directly to Pydantic models instead of dicts"""
    if not variables_overrides:
        return query

    if getattr(query, "kind", None) in WRAPPER_NODE_KINDS:
        source = apply_dashboard_variables(query.source, variables_overrides, team)
        return query.model_copy(update={"source": source})

    if getattr(query, "kind", None) == NodeKind.HOG_QL_QUERY:
        query_variables = getattr(query, "variables", None)
        if query_variables is None:
            return query

        updated_variables = query_variables.copy()
        for variable_id, overriden_hogql_variable in variables_overrides.items():
            query_variable: HogQLVariable = updated_variables.get(variable_id)

            if query_variable:
                updated_variables[variable_id] = HogQLVariable(
                    variableId=variable_id,
                    code_name=query_variable.code_name,
                    value=overriden_hogql_variable.get("value"),
                    isNull=overriden_hogql_variable.get("isNull"),
                )

        return query.model_copy(update={"variables": updated_variables})

    return query
