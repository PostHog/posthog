from datetime import timedelta
from typing import Dict, Optional, Any

from posthog.clickhouse.client.connection import Workload
from posthog.hogql import ast
from posthog.hogql.filters import replace_filters
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.models import Team
from posthog.schema import (
    HogQLQuery,
    HogQLQueryResponse,
    DashboardFilter,
    HogQLFilters,
    DateRange,
)


class HogQLQueryRunner(QueryRunner):
    query: HogQLQuery
    query_type = HogQLQuery

    def __init__(
        self,
        query: HogQLQuery | Dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        in_export_context: Optional[bool] = False,
    ):
        super().__init__(query, team, timings, in_export_context)
        if isinstance(query, HogQLQuery):
            self.query = query
        else:
            self.query = HogQLQuery.model_validate(query)

    def to_query(self) -> ast.SelectQuery:
        if self.timings is None:
            self.timings = HogQLTimings()
        values = (
            {key: ast.Constant(value=value) for key, value in self.query.values.items()} if self.query.values else None
        )
        with self.timings.measure("parse_select"):
            parsed_select = parse_select(str(self.query.query), timings=self.timings, placeholders=values)

        if self.query.filters:
            with self.timings.measure("filters"):
                placeholders_in_query = find_placeholders(parsed_select)
                if "filters" in placeholders_in_query:
                    parsed_select = replace_filters(parsed_select, self.query.filters, self.team)
        return parsed_select

    def to_persons_query(self) -> ast.SelectQuery:
        return self.to_query()

    def calculate(self) -> HogQLQueryResponse:
        return execute_hogql_query(
            query_type="HogQLQuery",
            query=self.to_query(),
            filters=self.query.filters,
            modifiers=self.query.modifiers,
            team=self.team,
            workload=Workload.ONLINE,
            timings=self.timings,
            in_export_context=self.in_export_context,
        )

    def _is_stale(self, cached_result_package):
        return True

    def _refresh_frequency(self):
        return timedelta(minutes=1)

    def apply_dashboard_filters(self, dashboard_filter: DashboardFilter) -> HogQLQuery:
        self.query.filters = self.query.filters or HogQLFilters()
        self.query.filters.dateRange = self.query.filters.dateRange or DateRange()

        if dashboard_filter.date_to or dashboard_filter.date_from:
            self.query.filters.dateRange.date_to = dashboard_filter.date_to
            self.query.filters.dateRange.date_from = dashboard_filter.date_from

        if dashboard_filter.properties:
            self.query.filters.properties = (self.query.filters.properties or []) + dashboard_filter.properties

        return self.query
