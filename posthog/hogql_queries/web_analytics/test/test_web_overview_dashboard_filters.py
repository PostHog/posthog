from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person

from posthog.schema import DashboardFilter, DateRange, EventPropertyFilter, WebOverviewQuery

from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.models.utils import uuid7


class TestWebOverviewDashboardFilters(ClickhouseTestMixin, APIBaseTest):
    def test_dashboard_filter_applies_when_no_existing_properties(self):
        query = WebOverviewQuery(dateRange=DateRange(date_from="-30d"), properties=[])
        runner = WebOverviewQueryRunner(team=self.team, query=query)

        runner.apply_dashboard_filters(
            DashboardFilter(properties=[EventPropertyFilter(key="$browser", value="Chrome", operator="exact")])
        )

        assert isinstance(runner.query.properties, list)
        assert len(runner.query.properties) == 1
        assert runner.query.properties[0].key == "$browser"

    def test_dashboard_filter_merges_with_existing_properties_as_list(self):
        # Regression test: apply_dashboard_filters was wrapping properties in PropertyGroupFilter,
        # but WebOverviewQuery.properties expects a list. This caused TypeError when
        # all_properties() tried to do: properties + _test_account_filters
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="-30d"),
            properties=[EventPropertyFilter(key="$pathname", value="/home", operator="exact")],
        )
        runner = WebOverviewQueryRunner(team=self.team, query=query)

        runner.apply_dashboard_filters(
            DashboardFilter(properties=[EventPropertyFilter(key="$browser", value="Chrome", operator="exact")])
        )

        assert isinstance(runner.query.properties, list)
        assert len(runner.query.properties) == 2
        assert runner.query.properties[0].key == "$pathname"
        assert runner.query.properties[1].key == "$browser"

    def test_dashboard_filter_with_existing_properties_executes(self):
        s1 = str(uuid7("2023-12-10"))
        with freeze_time("2023-12-10"):
            _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2023-12-10",
            properties={"$session_id": s1, "$pathname": "/home"},
        )

        query = WebOverviewQuery(
            dateRange=DateRange(date_from="-30d"),
            properties=[EventPropertyFilter(key="$pathname", value="/home", operator="exact")],
        )
        runner = WebOverviewQueryRunner(team=self.team, query=query)
        runner.apply_dashboard_filters(
            DashboardFilter(properties=[EventPropertyFilter(key="$browser", value="Chrome", operator="exact")])
        )

        with freeze_time("2023-12-15"):
            response = runner.calculate()

        assert response.results is not None
