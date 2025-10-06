from typing import Optional

from posthog.test.base import BaseTest

from posthog.schema import DashboardFilter, EventPropertyFilter, EventsQuery

from posthog.hogql_queries.events_query_runner import EventsQueryRunner


class TestEventsDashboardFilters(BaseTest):
    def _create_events_runner(
        self,
        *,
        after: Optional[str] = None,
        before: Optional[str] = None,
        properties: Optional[list[EventPropertyFilter]] = None,
    ) -> EventsQueryRunner:
        return EventsQueryRunner(
            query=EventsQuery(
                after=after,
                before=before,
                event="$pageview",
                kind="EventsQuery",
                orderBy=["timestamp ASC"],
                select=["*"],
                properties=properties,
            ),
            team=self.team,
        )

    def test_empty_dashboard_filters_change_nothing(self):
        query_runner = self._create_events_runner(after="-14d")
        query_runner.apply_dashboard_filters(DashboardFilter())

        assert query_runner.query.after == "-14d"
        assert query_runner.query.before is None
        assert query_runner.query.properties is None

    def test_date_from_override_updates_whole_date_range(self):
        query_runner = self._create_events_runner()
        query_runner.apply_dashboard_filters(DashboardFilter(date_from="-7d"))

        assert query_runner.query.after == "-7d"
        assert query_runner.query.before is None
        assert query_runner.query.properties is None

    def test_date_from_and_date_to_override_updates_whole_date_range(self):
        query_runner = self._create_events_runner(after="-7d")
        query_runner.apply_dashboard_filters(DashboardFilter(date_from="2024-07-07", date_to="2024-07-14"))

        assert query_runner.query.after == "2024-07-07"
        assert query_runner.query.before == "2024-07-14"
        assert query_runner.query.properties is None

    def test_properties_set_when_no_filters_present(self):
        query_runner = self._create_events_runner()
        query_runner.apply_dashboard_filters(
            DashboardFilter(properties=[EventPropertyFilter(key="key", value="value", operator="exact")])
        )

        assert query_runner.query.after is None
        assert query_runner.query.before is None
        assert query_runner.query.properties == [EventPropertyFilter(key="key", value="value", operator="exact")]

    def test_properties_list_extends_filters_list(self):
        query_runner = self._create_events_runner(
            properties=[EventPropertyFilter(key="abc", value="foo", operator="regex")]
        )
        query_runner.apply_dashboard_filters(
            DashboardFilter(properties=[EventPropertyFilter(key="xyz", value="bar", operator="regex")])
        )

        assert query_runner.query.after is None
        assert query_runner.query.before is None
        assert query_runner.query.properties == [
            EventPropertyFilter(key="abc", value="foo", operator="regex"),
            EventPropertyFilter(key="xyz", value="bar", operator="regex"),
        ]
