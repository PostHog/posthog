from sentry_sdk import capture_exception
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team
from posthog.schema import DashboardFilter, NodeKind

WRAPPER_NODE_KINDS = [NodeKind.DATA_TABLE_NODE, NodeKind.DATA_VISUALIZATION_NODE, NodeKind.INSIGHT_VIZ_NODE]


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
