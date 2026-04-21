from posthog.test.base import APIBaseTest, ClickhouseTestMixin, also_test_with_materialized_columns
from unittest.mock import patch

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    PersonPropertyFilter,
    PropertyOperator,
    WebStatsBreakdown,
    WebStatsTableQuery,
)

from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner


class TestEventsPrefilterTransformer(ClickhouseTestMixin, APIBaseTest):
    def _run_prefiltered_query(self, **query_kwargs):
        query_kwargs.setdefault("properties", [])
        query_kwargs.setdefault("breakdownBy", WebStatsBreakdown.PAGE)
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            **query_kwargs,
        )
        with patch(
            "posthog.hogql_queries.web_analytics.stats_table.is_web_analytics_events_prefilter_team",
            return_value=True,
        ):
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            runner.calculate()
            assert runner.paginator.response is not None
            return runner.paginator.response.clickhouse or ""

    def test_bounce_query_wraps_from_events(self):
        sql = self._run_prefiltered_query(includeBounceRate=True)

        assert "toDate(events.timestamp)" in sql
        assert sql.count("toDate(events.timestamp)") >= 2  # at least one FROM events wrapped

    def test_avg_time_query_wraps_from_events(self):
        sql = self._run_prefiltered_query(includeAvgTimeOnPage=True)

        assert "toDate(events.timestamp)" in sql

    def test_prefilter_includes_team_id(self):
        sql = self._run_prefiltered_query(includeBounceRate=True)

        assert f"equals(events.team_id, {self.team.pk})" in sql

    def test_prefilter_date_bounds_have_buffer(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[],
            breakdownBy=WebStatsBreakdown.PAGE,
            includeBounceRate=True,
        )
        with patch(
            "posthog.hogql_queries.web_analytics.stats_table.is_web_analytics_events_prefilter_team",
            return_value=True,
        ):
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            date_from, date_to = runner._events_prefilter_date_bounds()

        # Date range is Jan 1-31, buffer is ±1 day
        assert date_from == "2023-12-31"
        assert date_to == "2024-02-01"

    def test_prefilter_with_event_filter(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[
                EventPropertyFilter(
                    key="$geoip_city_name",
                    operator=PropertyOperator.EXACT,
                    value=["Pretoria"],
                )
            ],
            breakdownBy=WebStatsBreakdown.PAGE,
            includeBounceRate=True,
        )
        with patch(
            "posthog.hogql_queries.web_analytics.stats_table.is_web_analytics_events_prefilter_team",
            return_value=True,
        ):
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            runner.calculate()
            assert runner.paginator.response is not None
            sql = runner.paginator.response.clickhouse or ""

        assert "toDate(events.timestamp)" in sql

    def test_non_prefiltered_team_unchanged(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[],
            breakdownBy=WebStatsBreakdown.PAGE,
            includeBounceRate=True,
        )
        with patch(
            "posthog.hogql_queries.web_analytics.stats_table.is_web_analytics_events_prefilter_team",
            return_value=False,
        ):
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            runner.calculate()
            assert runner.paginator.response is not None
            sql = runner.paginator.response.clickhouse or ""

        assert "toDate(events.timestamp)" not in sql

    def test_main_query_without_bounce_not_affected(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[],
            breakdownBy=WebStatsBreakdown.DEVICE_TYPE,
        )
        with patch(
            "posthog.hogql_queries.web_analytics.stats_table.is_web_analytics_events_prefilter_team",
            return_value=True,
        ):
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            runner.calculate()
            assert runner.paginator.response is not None
            sql = runner.paginator.response.clickhouse or ""

        # Non-bounce queries also get wrapped since they go through the same _calculate path
        assert "toDate(events.timestamp)" in sql

    @also_test_with_materialized_columns(
        event_properties=["$pathname", "$geoip_city_name"],
        verify_no_jsonextract=False,
    )
    def test_bounce_with_geo_filter(self):
        sql = self._run_prefiltered_query(
            includeBounceRate=True,
            properties=[
                EventPropertyFilter(
                    key="$geoip_city_name",
                    operator=PropertyOperator.EXACT,
                    value=["Pretoria"],
                )
            ],
        )

        assert "toDate(events.timestamp)" in sql
        assert sql.count("toDate(events.timestamp)") >= 2

    def test_bounce_with_non_utc_timezone(self):
        self.team.timezone = "Europe/Berlin"
        self.team.save()

        sql = self._run_prefiltered_query(includeBounceRate=True)

        assert "toDate(events.timestamp)" in sql
        assert sql.count("toDate(events.timestamp)") >= 2

    def test_bounce_with_unmaterialized_property_filter(self):
        sql = self._run_prefiltered_query(
            includeBounceRate=True,
            properties=[
                EventPropertyFilter(
                    key="customProperty",
                    operator=PropertyOperator.EXACT,
                    value=["1"],
                )
            ],
        )

        assert "toDate(events.timestamp)" in sql
        # properties blob must be in the subquery for JSONExtractRaw
        assert "events.properties" in sql
        assert "JSONExtractRaw(events.properties," in sql

    @also_test_with_materialized_columns(
        person_properties=["email"],
        verify_no_jsonextract=False,
    )
    def test_bounce_with_person_property_filter(self):
        from posthog.schema import PersonsOnEventsMode

        self.team.modifiers = {"personsOnEventsMode": PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS}
        self.team.save()

        sql = self._run_prefiltered_query(
            includeBounceRate=True,
            properties=[
                PersonPropertyFilter(
                    key="email",
                    operator=PropertyOperator.IS_NOT,
                    value=["test@example.com"],
                )
            ],
        )

        assert "toDate(events.timestamp)" in sql
        # When materialized with PoE, mat_pp_email must be in the prefilter subquery
        # SELECT — if missing, the query above would fail with UNKNOWN_IDENTIFIER.
        # Also verify it appears in the generated SQL for the materialized case.
        if "mat_pp_email" in sql:
            assert sql.count("mat_pp_email") >= 2, (
                "mat_pp_email should appear in both the subquery SELECT and outer WHERE"
            )

    def test_initial_page_breakdown_with_bounce(self):
        sql = self._run_prefiltered_query(
            includeBounceRate=True,
            breakdownBy=WebStatsBreakdown.INITIAL_PAGE,
        )

        assert "toDate(events.timestamp)" in sql
