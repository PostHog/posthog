import json
from typing import Any

import posthoganalytics

from posthog.schema import DashboardFilter, HogQLVariable, NodeKind

from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team

WRAPPER_NODE_KINDS = [NodeKind.DATA_TABLE_NODE, NodeKind.DATA_VISUALIZATION_NODE, NodeKind.INSIGHT_VIZ_NODE]

# Fields where a tile override replaces the dashboard value outright when set.
# Property filters are handled separately (merged per key).
_TILE_SCALAR_OVERRIDE_FIELDS = ["breakdown_filter", "interval", "filterTestAccounts"]

TILE_FILTER_MERGE_FLAG = "dashboard-tile-filter-merge"


def tile_filter_merge_enabled(team: Team) -> bool:
    """Gates the tile-filters-merge-with-dashboard-filters behavior (`merge_dashboard_and_tile_filters`).
    Off, tile overrides replace dashboard filters wholesale, matching pre-merge behavior."""
    return bool(
        posthoganalytics.feature_enabled(
            TILE_FILTER_MERGE_FLAG,
            str(team.uuid),
            groups={"organization": str(team.organization_id), "project": str(team.id)},
        )
    )


def _property_identity(prop: dict) -> tuple[str, Any]:
    """The (type, key) a property filter targets — the unit at which a tile takes precedence.
    `type` defaults to "event" to match how untyped property filters are interpreted downstream.
    `key` is coerced to a hashable form since it comes from unvalidated client JSON and must be
    usable in a set/dict — an unhashable key (e.g. a list) would otherwise raise TypeError."""
    key = prop.get("key")
    if isinstance(key, (list, dict)):
        key = json.dumps(key, sort_keys=True)
    return (prop.get("type") or "event", key)


def merge_dashboard_and_tile_filters(dashboard_filters: dict | None, tile_filters: dict | None) -> dict:
    """Merge a tile's filter overrides on top of the dashboard-level filters.

    The tile wins per field. Scalars (breakdown, interval, test-account filtering) are replaced outright
    when the tile sets them. Property filters merge per (type, key): a tile property replaces the
    dashboard's filter on the same key, while non-overlapping keys from both layers are kept and
    AND-combined. The date range is treated as one unit — a tile that sets either bound supplies both
    bounds and explicitDate, so a tile date_from is never paired with a stale dashboard date_to or a
    stale dashboard explicitDate.

    Overriding the insight's own base filters (not just the dashboard's) is handled separately by
    `remove_query_properties_overridden_by_tile`, which the tile-aware call sites apply to the query.

    The frontend re-derives this same precedence in `getEffectiveFilterOverrides` (InsightDetails.tsx)
    to attribute each shown filter to its source; keep the two in step when changing the tie-break here.
    """
    if not tile_filters:
        return dashboard_filters or {}
    if not dashboard_filters:
        return tile_filters or {}

    merged = {**dashboard_filters}

    for field in _TILE_SCALAR_OVERRIDE_FIELDS:
        if tile_filters.get(field) is not None:
            merged[field] = tile_filters[field]

    if tile_filters.get("date_from") is not None or tile_filters.get("date_to") is not None:
        merged["date_from"] = tile_filters.get("date_from")
        merged["date_to"] = tile_filters.get("date_to")
        # The date range is one unit — drop the dashboard's explicitDate before adopting the tile's.
        merged.pop("explicitDate", None)
        if tile_filters.get("explicitDate") is not None:
            merged["explicitDate"] = tile_filters["explicitDate"]

    tile_props = tile_filters.get("properties") or []
    dashboard_props = dashboard_filters.get("properties") or []
    tile_keys = {_property_identity(p) for p in tile_props}
    combined_properties = [p for p in dashboard_props if _property_identity(p) not in tile_keys] + tile_props
    if combined_properties:
        merged["properties"] = combined_properties

    return merged


def _without_keys(properties: Any, keys: set[tuple[str, Any]]) -> Any:
    """Drop leaf property filters whose (type, key) is in `keys` from a query's `properties`, which is
    either a flat list of leaves or a `PropertyGroupFilter` dict (a group of `PropertyGroupFilterValue`
    subgroups, themselves arbitrarily nested — AND of ORs of ANDs, etc). Recurses into every nested
    subgroup rather than stopping at one level, since leaves can sit at any depth. Emptied subgroups
    are pruned."""
    if isinstance(properties, list):
        return [p for p in properties if _property_identity(p) not in keys]
    if isinstance(properties, dict) and isinstance(properties.get("values"), list):
        new_values = []
        for value in properties["values"]:
            if isinstance(value, dict) and isinstance(value.get("values"), list):
                pruned = _without_keys(value, keys)
                if pruned["values"]:
                    new_values.append(pruned)
            elif not (isinstance(value, dict) and _property_identity(value) in keys):
                new_values.append(value)
        return {**properties, "values": new_values}
    return properties


def _strip_query_properties(query: dict, keys: set[tuple[str, Any]]) -> dict:
    if query.get("kind") in WRAPPER_NODE_KINDS:
        return {**query, "source": _strip_query_properties(query["source"], keys)}
    if query.get("properties") is not None:
        query = {**query, "properties": _without_keys(query["properties"], keys)}
    filters = query.get("filters")
    if isinstance(filters, dict) and filters.get("properties") is not None:
        query = {**query, "filters": {**filters, "properties": _without_keys(filters["properties"], keys)}}
    return query


def remove_query_properties_overridden_by_tile(query: dict, tile_filters: dict | None) -> dict:
    """Drop the insight's own property filters that a tile override replaces on the same (type, key),
    so a tile filter takes precedence over the insight's base filter instead of merely AND-ing with it.
    Only the tile layer gets this precedence — dashboard-level filters still stack onto the insight."""
    tile_props = (tile_filters or {}).get("properties") or []
    keys = {_property_identity(p) for p in tile_props}
    if not keys:
        return query
    return _strip_query_properties(query, keys)


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
