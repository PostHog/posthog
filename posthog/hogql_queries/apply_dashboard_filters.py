from typing import Any, TypedDict

from posthog.schema import DashboardFilter, HogQLVariable, NodeKind

from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.hogql_queries.utils.dashboard_filter_conflicts import filters_contradict
from posthog.models import Team

WRAPPER_NODE_KINDS = [NodeKind.DATA_TABLE_NODE, NodeKind.DATA_VISUALIZATION_NODE, NodeKind.INSIGHT_VIZ_NODE]
_DATA_WAREHOUSE_NODE_KINDS = {"DataWarehouseNode", "FunnelsDataWarehouseNode", "LifecycleDataWarehouseNode"}

# Fields where the higher-priority (override) layer replaces the lower-priority (base) value outright
# when set. Property filters are handled separately (stacked unless they contradict).
_SCALAR_OVERRIDE_FIELDS = ["breakdown_filter", "interval", "filterTestAccounts"]


class FilterLayerResolution(TypedDict):
    dashboard: dict
    tile: dict
    overridden_dashboard: dict


def resolve_filter_layers_by_priority(
    base_filters: dict | None, override_filters: dict | None
) -> FilterLayerResolution:
    base = base_filters or {}
    override = override_filters or {}
    effective_base = {**base}
    overridden_base: dict = {}

    for field in _SCALAR_OVERRIDE_FIELDS:
        if override.get(field) is not None:
            effective_base.pop(field, None)
            if base.get(field) is not None:
                overridden_base[field] = base[field]

    if override.get("date_from") is not None or override.get("date_to") is not None:
        if base.get("date_from") is not None or base.get("date_to") is not None:
            overridden_base["date_from"] = base.get("date_from")
            overridden_base["date_to"] = base.get("date_to")
            if base.get("explicitDate") is not None:
                overridden_base["explicitDate"] = base["explicitDate"]
        effective_base.pop("date_from", None)
        effective_base.pop("date_to", None)
        effective_base.pop("explicitDate", None)

    override_props = override.get("properties") or []
    base_props = base.get("properties") or []
    contradicted_base = []
    surviving_base = []
    for base_property in base_props:
        if any(filters_contradict(base_property, override_property) for override_property in override_props):
            contradicted_base.append(base_property)
        else:
            surviving_base.append(base_property)
    if contradicted_base:
        overridden_base["properties"] = contradicted_base
    if base_props:
        if surviving_base:
            effective_base["properties"] = surviving_base
        else:
            effective_base.pop("properties", None)

    return {
        "dashboard": effective_base,
        "tile": override,
        "overridden_dashboard": overridden_base,
    }


def merge_filters_by_priority(base_filters: dict | None, override_filters: dict | None) -> dict:
    """Merge two filter layers, with `override_filters` taking priority over `base_filters`.

    The override wins per field. Scalars (breakdown, interval, test-account filtering) are replaced
    outright when the override sets them. Property filters stack (AND-combine) by default, since two
    filters on the same key can still describe a valid set (e.g. `utm_source = google` and
    `utm_source is set`). A base property is dropped only when an override property provably contradicts
    it — ANDing them could never match — in which case the override wins. The date range is treated as
    one unit — an override that sets either bound supplies both bounds and explicitDate, so an override
    date_from is never paired with a stale base date_to or a stale base explicitDate.

    Callers today use this for the dashboard/tile layer pair (dashboard as base, tile as override), but
    the algorithm itself is generic priority merging and isn't tied to that pairing.

    Overriding the insight's own base filters (not just the lower-priority layer's) is handled separately
    by `remove_query_properties_overridden_by`, which the override-aware call sites apply to the query.
    """
    if not override_filters:
        return base_filters or {}
    if not base_filters:
        return override_filters or {}

    resolved_layers = resolve_filter_layers_by_priority(base_filters, override_filters)
    merged = {**resolved_layers["dashboard"]}

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
    combined_properties = (resolved_layers["dashboard"].get("properties") or []) + override_props
    if combined_properties:
        merged["properties"] = combined_properties

    return merged


def _without_contradicted(properties: Any, overriding_props: list[dict]) -> Any:
    """Drop leaf property filters that any `overriding_props` filter provably contradicts from a query's
    `properties`, which is either a flat list of leaves or a `PropertyGroupFilter` dict (a group of
    `PropertyGroupFilterValue` subgroups, themselves arbitrarily nested — AND of ORs of ANDs, etc).
    Recurses into every nested subgroup rather than stopping at one level, since leaves can sit at any
    depth. Emptied subgroups are pruned."""

    def is_contradicted(leaf: Any) -> bool:
        return isinstance(leaf, dict) and any(filters_contradict(leaf, o) for o in overriding_props)

    if isinstance(properties, list):
        return [p for p in properties if not is_contradicted(p)]
    if isinstance(properties, dict) and isinstance(properties.get("values"), list):
        new_values = []
        for value in properties["values"]:
            if isinstance(value, dict) and isinstance(value.get("values"), list):
                pruned = _without_contradicted(value, overriding_props)
                if pruned["values"]:
                    new_values.append(pruned)
            elif not is_contradicted(value):
                new_values.append(value)
        return {**properties, "values": new_values}
    return properties


def _strip_query_properties(query: dict, overriding_props: list[dict]) -> dict:
    if query.get("kind") in WRAPPER_NODE_KINDS:
        return {**query, "source": _strip_query_properties(query["source"], overriding_props)}
    if query.get("properties") is not None:
        query = {**query, "properties": _without_contradicted(query["properties"], overriding_props)}
    series = query.get("series")
    if isinstance(series, list):
        query = {
            **query,
            "series": [
                (
                    {**node, "properties": _without_contradicted(node["properties"], overriding_props)}
                    if isinstance(node, dict) and node.get("properties") is not None
                    else node
                )
                for node in series
            ],
        }
    filters = query.get("filters")
    if isinstance(filters, dict) and filters.get("properties") is not None:
        query = {
            **query,
            "filters": {**filters, "properties": _without_contradicted(filters["properties"], overriding_props)},
        }
    return query


def remove_query_properties_overridden_by(query: dict, overriding_filters: dict | None) -> dict:
    """Drop the insight's own property filters that an `overriding_filters` property provably contradicts,
    so the higher-priority layers take precedence over the insight's base filter instead of AND-ing a
    contradiction into an empty result. Compatible filters on the same key are left in place to stack.
    Callers pass the effective dashboard + tile filter set, so both layers can override the insight's own
    filter."""
    # Dashboard/tile filters are raw JSON from the DB, never validated against the schema, so a property
    # entry can be a bare string (legacy or malformed data). Keep only dicts before comparing.
    overriding_props = [p for p in ((overriding_filters or {}).get("properties") or []) if isinstance(p, dict)]
    if not overriding_props:
        return query
    return _strip_query_properties(query, overriding_props)


def _has_data_warehouse_series(query: dict) -> bool:
    if query.get("kind") in WRAPPER_NODE_KINDS:
        return _has_data_warehouse_series(query["source"])
    series = query.get("series")
    return isinstance(series, list) and any(
        isinstance(node, dict) and node.get("kind") in _DATA_WAREHOUSE_NODE_KINDS for node in series
    )


def resolve_effective_dashboard_filters(
    query: dict, base_filters: dict | None, tile_filters_override: dict | None
) -> tuple[dict, dict]:
    """Combine dashboard and tile filters for query execution and display reconstruction."""
    effective_filters = (
        merge_filters_by_priority(base_filters, tile_filters_override) if tile_filters_override else base_filters or {}
    )
    if effective_filters and not _has_data_warehouse_series(query):
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
