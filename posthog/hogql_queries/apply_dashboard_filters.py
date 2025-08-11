from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team
from posthog.schema import BreakdownType, DashboardFilter, HogQLVariable, MultipleBreakdownType, NodeKind
from typing import Any

WRAPPER_NODE_KINDS = [NodeKind.DATA_TABLE_NODE, NodeKind.DATA_VISUALIZATION_NODE, NodeKind.INSIGHT_VIZ_NODE]


def _migrate_breakdown_fields(filters: dict) -> dict:
    """
    Migrate deprecated breakdown fields from BreakdownFilter to the new breakdowns array format.

    Converts:
    - breakdown -> breakdowns[0].property
    - breakdown_normalize_url -> breakdowns[0].normalize_url
    - breakdown_histogram_bin_count -> breakdowns[0].histogram_bin_count
    - breakdown_type -> breakdowns[0].type
    - breakdown_group_type_index -> breakdowns[0].group_type_index
    """
    breakdown_filter = filters.get("breakdown_filter")
    if not breakdown_filter or not isinstance(breakdown_filter, dict):
        return filters

    # Check if legacy breakdown field exists
    if breakdown_filter.get("breakdown") is not None:
        if not breakdown_filter.get("breakdowns"):
            # Create new Breakdown object from legacy fields when breakdowns array is empty
            breakdown_obj = {"property": str(breakdown_filter["breakdown"])}

            # Map deprecated fields to new structure
            if breakdown_filter.get("breakdown_normalize_url") is not None:
                breakdown_obj["normalize_url"] = breakdown_filter["breakdown_normalize_url"]
            if breakdown_filter.get("breakdown_histogram_bin_count") is not None:
                breakdown_obj["histogram_bin_count"] = breakdown_filter["breakdown_histogram_bin_count"]
            if breakdown_filter.get("breakdown_group_type_index") is not None:
                breakdown_obj["group_type_index"] = breakdown_filter["breakdown_group_type_index"]

            # Map breakdown_type to type with appropriate enum conversion
            if breakdown_filter.get("breakdown_type"):
                breakdown_type = breakdown_filter["breakdown_type"]
                # Convert BreakdownType to MultipleBreakdownType
                type_mapping = {
                    BreakdownType.PERSON: MultipleBreakdownType.PERSON,
                    BreakdownType.EVENT: MultipleBreakdownType.EVENT,
                    BreakdownType.EVENT_METADATA: MultipleBreakdownType.EVENT_METADATA,
                    BreakdownType.GROUP: MultipleBreakdownType.GROUP,
                    BreakdownType.SESSION: MultipleBreakdownType.SESSION,
                    BreakdownType.HOGQL: MultipleBreakdownType.HOGQL,
                }
                if breakdown_type in type_mapping:
                    breakdown_obj["type"] = type_mapping[breakdown_type]

            # Create updated breakdown_filter with breakdowns array
            updated_breakdown_filter = breakdown_filter.copy()
            updated_breakdown_filter["breakdowns"] = [breakdown_obj]
        else:
            # If breakdowns array is already populated, just create a copy
            updated_breakdown_filter = breakdown_filter.copy()

        # Clear the deprecated fields since we're migrating to breakdowns array
        updated_breakdown_filter.pop("breakdown", None)
        updated_breakdown_filter.pop("breakdown_normalize_url", None)
        updated_breakdown_filter.pop("breakdown_histogram_bin_count", None)
        updated_breakdown_filter.pop("breakdown_group_type_index", None)
        updated_breakdown_filter.pop("breakdown_type", None)

        # Create updated filters dict
        updated_filters = filters.copy()
        updated_filters["breakdown_filter"] = updated_breakdown_filter
        return updated_filters

    return filters


# Apply the filters from the django-style Dashboard object
def apply_dashboard_filters_to_dict(query: dict, filters: dict, team: Team) -> dict:
    if not filters:
        return query

    # Migrate deprecated breakdown fields to breakdowns array
    filters = _migrate_breakdown_fields(filters)

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


def _migrate_breakdown_fields_pydantic(filters: DashboardFilter) -> DashboardFilter:
    """
    Migrate deprecated breakdown fields from BreakdownFilter to the new breakdowns array format for Pydantic models.
    Uses the dict-based migration function and converts back to Pydantic models.
    """
    if not filters.breakdown_filter:
        return filters

    # Convert to dict, apply migration, then convert back to Pydantic
    filters_dict = filters.model_dump()
    migrated_filters_dict = _migrate_breakdown_fields(filters_dict)

    # If no changes were made, return the original
    if migrated_filters_dict == filters_dict:
        return filters

    # Convert back to Pydantic model
    return DashboardFilter(**migrated_filters_dict)


def apply_dashboard_filters(query: Any, filters: DashboardFilter, team: Team) -> Any:
    """Apply dashboard filters directly to Pydantic models instead of dicts"""
    if not filters:
        return query

    # Migrate deprecated breakdown fields to breakdowns array
    filters = _migrate_breakdown_fields_pydantic(filters)

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
