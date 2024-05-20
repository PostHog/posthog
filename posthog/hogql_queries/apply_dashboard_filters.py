from sentry_sdk import capture_exception
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team
from posthog.schema import DashboardFilter, NodeKind

WRAPPER_NODE_KINDS = [NodeKind.DataTableNode, NodeKind.DataVisualizationNode, NodeKind.InsightVizNode]


# Apply the filters from the django-style Dashboard object
def apply_dashboard_filters(query: dict, filters: dict, team: Team) -> dict:
    kind = query.get("kind", None)

    if kind in WRAPPER_NODE_KINDS:
        source = apply_dashboard_filters(query["source"], filters, team)
        return {**query, "source": source}

    try:
        query_runner = get_query_runner(query, team)
    except ValueError:
        capture_exception()
        return query

    query_runner.apply_dashboard_filters(DashboardFilter(**filters))
    return query_runner.query.model_dump()
