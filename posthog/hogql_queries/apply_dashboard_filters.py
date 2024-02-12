from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team
from posthog.schema import DashboardFilter


# Apply the filters from the django-style Dashboard object
def apply_dashboard_filters(query: dict, filters: dict, team: Team) -> dict:
    kind = query.get("kind", None)

    if kind == "DataTableNode":
        source = apply_dashboard_filters(query["source"], filters, team)
        return {**query, "source": source}

    try:
        query_runner = get_query_runner(query, team)
    except ValueError:
        return query
    try:
        return query_runner.apply_dashboard_filters(DashboardFilter(**filters)).dict()
    except NotImplementedError:
        # TODO when we implement apply_dashboard_filters on more query runners, we can remove the try/catch
        return query
