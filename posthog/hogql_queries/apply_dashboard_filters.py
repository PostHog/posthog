import json
from typing import Any

from posthog.schema import DashboardFilter, HogQLVariable, NodeKind

from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team

WRAPPER_NODE_KINDS = [NodeKind.DATA_TABLE_NODE, NodeKind.DATA_VISUALIZATION_NODE, NodeKind.INSIGHT_VIZ_NODE]

# Fields where the higher-priority (override) layer replaces the lower-priority (base) value outright
# when set. Property filters are handled separately (merged per key).
_SCALAR_OVERRIDE_FIELDS = ["breakdown_filter", "interval", "filterTestAccounts"]


def _property_identity(prop: dict) -> tuple[str, Any, Any]:
    """The (type, group_type_index, key) a property filter targets — the unit at which one layer takes
    precedence over another. `type` defaults to "event" to match how untyped property filters are
    interpreted downstream. `group_type_index` keeps two group types with the same key distinct, so a
    tile override on one group type doesn't shadow the same key on another. `key` is coerced to a hashable
    form since it comes from unvalidated client JSON and must be usable in a set/dict — an unhashable key
    (e.g. a list) would otherwise raise TypeError."""
    key = prop.get("key")
    if isinstance(key, (list, dict)):
        key = json.dumps(key, sort_keys=True)
    return (prop.get("type") or "event", prop.get("group_type_index"), key)


def merge_filters_by_priority(base_filters: dict | None, override_filters: dict | None) -> dict:
    """Merge two filter layers, with `override_filters` taking priority over `base_filters`.

    The override wins per field. Scalars (breakdown, interval, test-account filtering) are replaced
    outright when the override sets them. Property filters merge per (type, key): an override property
    replaces the base's filter on the same key, while non-overlapping keys from both layers are kept and
    AND-combined. The date range is treated as one unit — an override that sets either bound supplies
    both bounds and explicitDate, so an override date_from is never paired with a stale base date_to or
    a stale base explicitDate.

    Callers today use this for the dashboard/tile layer pair (dashboard as base, tile as override), but
    the algorithm itself is generic priority merging and isn't tied to that pairing.

    Overriding the insight's own base filters (not just the lower-priority layer's) is handled separately
    by `remove_query_properties_overridden_by`, which the override-aware call sites apply to the query.

    The frontend re-derives this precedence in `insightDetailsFilterOverrides.ts` purely to attribute each
    shown filter to its source (display only); keep that tie-break in step when changing this one.
    """
    if not override_filters:
        return base_filters or {}
    if not base_filters:
        return override_filters or {}

    merged = {**base_filters}

    for field in _SCALAR_OVERRIDE_FIELDS:
        if override_filters.get(field) is not None:
            merged[field] = override_filters[field]

    if override_filters.get("date_from") is not None or override_filters.get("date_to") is not None:
        merged["date_from"] = override_filters.get("date_from")
        merged["date_to"] = override_filters.get("date_to")
        # The date range is one unit — drop the base's explicitDate before adopting the override's.
        merged.pop("explicitDate", None)
        if override_filters.get("explicitDate") is not None:
            merged["explicitDate"] = override_filters["explicitDate"]

    override_props = override_filters.get("properties") or []
    base_props = base_filters.get("properties") or []
    override_keys = {_property_identity(p) for p in override_props}
    combined_properties = [p for p in base_props if _property_identity(p) not in override_keys] + override_props
    if combined_properties:
        merged["properties"] = combined_properties

    return merged


def _without_keys(properties: Any, keys: set[tuple[str, Any, Any]]) -> Any:
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


def _strip_query_properties(query: dict, keys: set[tuple[str, Any, Any]]) -> dict:
    if query.get("kind") in WRAPPER_NODE_KINDS:
        return {**query, "source": _strip_query_properties(query["source"], keys)}
    if query.get("properties") is not None:
        query = {**query, "properties": _without_keys(query["properties"], keys)}
    filters = query.get("filters")
    if isinstance(filters, dict) and filters.get("properties") is not None:
        query = {**query, "filters": {**filters, "properties": _without_keys(filters["properties"], keys)}}
    return query


def remove_query_properties_overridden_by(query: dict, overriding_filters: dict | None) -> dict:
    """Drop the insight's own property filters that `overriding_filters` replaces on the same (type, key),
    so the higher-priority layers take precedence over the insight's base filter instead of merely AND-ing
    with it (which could AND a contradiction into an empty result). Callers pass the effective dashboard +
    tile filter set, so both layers override the insight's own filter on a shared key."""
    overriding_props = (overriding_filters or {}).get("properties") or []
    keys = {_property_identity(p) for p in overriding_props}
    if not keys:
        return query
    return _strip_query_properties(query, keys)


def resolve_effective_dashboard_filters(
    query: dict, base_filters: dict | None, tile_filters_override: dict | None
) -> tuple[dict, dict]:
    """Combine the dashboard-level `base_filters` with a tile's `tile_filters_override` into the filter set
    that actually applies, and strip any of the insight's own property filters that set replaces on a
    shared key. Both the "compute the query" and "reconstruct it for display" call sites need this same
    dashboard+tile+insight precedence resolved identically, so it lives here once rather than being
    re-derived at each call site.

    Returns `(query, effective_filters)` — callers still apply `effective_filters` to the query themselves
    via `apply_dashboard_filters_to_dict`.
    """
    effective_filters = (
        merge_filters_by_priority(base_filters, tile_filters_override) if tile_filters_override else base_filters or {}
    )

    if effective_filters:
        query = remove_query_properties_overridden_by(query, effective_filters)

    return query, effective_filters


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
