from posthog.schema import HogQLQuery, DashboardFilter, HogQLFilters, DateRange


# Apply the filters from the django-style Dashboard object
def apply_dashboard_filters(query: dict, filters: dict) -> dict:
    kind = query.get("kind", None)

    if kind == "DataTableNode":
        source = apply_dashboard_filters(query["source"], filters)
        return {**query, "source": source}

    dashboard_filter = DashboardFilter(**filters)

    if kind == "HogQLQuery":
        node = HogQLQuery(**query)

        hogql_filters = node.filters or HogQLFilters()
        date_range = hogql_filters.dateRange or DateRange()
        node.filters = hogql_filters
        hogql_filters.dateRange = date_range

        if dashboard_filter.date_to:
            date_range.date_to = dashboard_filter.date_to
        if dashboard_filter.date_from:
            date_range.date_from = dashboard_filter.date_from

        return node.dict()
    else:
        return query
