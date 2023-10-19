from posthog.models import Team
from posthog.schema import DashboardFilter


# Apply the filters from the django-style Dashboard object
def apply_dashboard_filters(query: dict, filters: dict, team: Team) -> dict:
    kind = query.get("kind", None)

    if kind == "DataTableNode":
        source = apply_dashboard_filters(query["source"], filters, team)
        return {**query, "source": source}

    dashboard_filter = DashboardFilter(**filters)

    if kind == "HogQLQuery":
        from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

        query_runner = HogQLQueryRunner(query, team)
        return query_runner.apply_dashboard_filters(dashboard_filter).dict()
    else:
        return query
