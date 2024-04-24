from sentry_sdk import capture_exception
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team
from posthog.schema import DashboardFilter, NodeKind

DATA_TABLE_LIKE_NODE_KINDS = [NodeKind.DataTableNode, NodeKind.DataVisualizationNode]


# Apply the filters from the django-style Dashboard object
def apply_dashboard_filters_to_dict(query: dict, filters: dict, team: Team) -> dict:
    if not filters:
        return query

    if query.get("kind") in DATA_TABLE_LIKE_NODE_KINDS:
        source = apply_dashboard_filters_to_dict(query["source"], filters, team)
        return {**query, "source": source}

    try:
        query_runner = get_query_runner(query, team)
    except ValueError:
        capture_exception()
        return query
    return query_runner.apply_dashboard_filters(DashboardFilter(**filters)).dict()
