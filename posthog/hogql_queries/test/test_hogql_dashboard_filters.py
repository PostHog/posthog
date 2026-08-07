from typing import Optional

from posthog.test.base import BaseTest

from posthog.schema import (
    BreakdownFilter,
    DashboardFilter,
    DateRange,
    EventPropertyFilter,
    HogQLFilters,
    HogQLQuery,
    IntervalType,
)

from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner


class TestHogQLDashboardFilters(BaseTest):
    def _create_hogql_runner(
        self, query: str = "SELECT uuid FROM events", filters: Optional[HogQLFilters] = None
    ) -> HogQLQueryRunner:
        return HogQLQueryRunner(team=self.team, query=HogQLQuery(query=query, filters=filters))

    def test_empty_dashboard_filters_change_nothing(self):
        query_runner = self._create_hogql_runner()
        query_runner.apply_dashboard_filters(DashboardFilter())

        assert query_runner.query.filters == HogQLFilters()

    def test_date_from_override_updates_whole_date_range(self):
        query_runner = self._create_hogql_runner()
        query_runner.apply_dashboard_filters(DashboardFilter(date_from="-14d"))

        assert query_runner.query.filters == HogQLFilters(dateRange=DateRange(date_from="-14d", date_to=None))

    def test_date_from_and_date_to_override_updates_whole_date_range(self):
        query_runner = self._create_hogql_runner(
            filters=HogQLFilters(dateRange=DateRange(date_from="-7d", date_to=None))
        )
        query_runner.apply_dashboard_filters(DashboardFilter(date_from="2024-07-07", date_to="2024-07-14"))

        assert query_runner.query.filters == HogQLFilters(
            dateRange=DateRange(date_from="2024-07-07", date_to="2024-07-14")
        )

    def test_properties_set_when_no_filters_present(self):
        query_runner = self._create_hogql_runner()
        query_runner.apply_dashboard_filters(
            DashboardFilter(properties=[EventPropertyFilter(key="key", value="value", operator="exact")])
        )

        assert query_runner.query.filters == HogQLFilters(
            properties=[EventPropertyFilter(key="key", value="value", operator="exact")]
        )

    def test_properties_list_extends_filters_list(self):
        query_runner = self._create_hogql_runner(
            filters=HogQLFilters(properties=[EventPropertyFilter(key="abc", value="foo", operator="regex")])
        )
        query_runner.apply_dashboard_filters(
            DashboardFilter(properties=[EventPropertyFilter(key="xyz", value="bar", operator="regex")])
        )

        assert query_runner.query.filters == HogQLFilters(
            properties=[
                EventPropertyFilter(key="abc", value="foo", operator="regex"),
                EventPropertyFilter(key="xyz", value="bar", operator="regex"),
            ]
        )

    def test_interval_is_copied_for_the_interval_placeholder(self):
        query_runner = self._create_hogql_runner()
        query_runner.apply_dashboard_filters(DashboardFilter(interval=IntervalType.WEEK))

        assert query_runner.query.filters == HogQLFilters(interval=IntervalType.WEEK)

    def test_breakdown_filter_is_copied_for_the_breakdown_placeholder(self):
        breakdown_filter = BreakdownFilter(breakdown="plan", breakdown_type="event")
        query_runner = self._create_hogql_runner()
        query_runner.apply_dashboard_filters(DashboardFilter(breakdown_filter=breakdown_filter))

        assert query_runner.query.filters == HogQLFilters(breakdownFilter=breakdown_filter)
