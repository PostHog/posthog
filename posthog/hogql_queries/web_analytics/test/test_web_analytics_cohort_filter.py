from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import (
    CohortPropertyFilter,
    DateRange,
    HogQLQueryModifiers,
    WebGoalsQuery,
    WebOverviewQuery,
    WebStatsBreakdown,
    WebStatsTableQuery,
)

from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.hogql_queries.web_analytics.web_goals import WebGoalsQueryRunner
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.models import Action, Cohort
from posthog.models.utils import uuid7


class TestWebAnalyticsCohortFilter(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2026-01-29"

    def _create_cohort_with_person(self, person_id: str, cohort_name: str = "Test Cohort"):
        cohort = Cohort.objects.create(
            team=self.team,
            name=cohort_name,
            groups=[{"properties": [{"key": "name", "value": person_id, "type": "person"}]}],
        )
        cohort.calculate_people_ch(pending_version=0)
        return cohort

    def _create_events(self, data, event="$pageview"):
        person_result = []
        for id, timestamps in data:
            with freeze_time(timestamps[0][0]):
                person_result.append(
                    _create_person(
                        team_id=self.team.pk,
                        distinct_ids=[id],
                        properties={"name": id},
                    )
                )
            for timestamp, session_id, *extra in timestamps:
                url = extra[0] if extra else None
                properties = extra[1] if extra and len(extra) > 1 else {}

                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=id,
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$pathname": url,
                        "$current_url": f"http://posthog.com{url}" if url else None,
                        **properties,
                    },
                )
        return person_result

    def _run_web_overview_query(
        self,
        date_from: str,
        date_to: str,
        cohort_id: int | None = None,
        use_preaggregated: bool = False,
    ):
        with freeze_time(self.QUERY_TIMESTAMP):
            properties = []
            if cohort_id is not None:
                properties.append(CohortPropertyFilter(key="id", value=cohort_id, type="cohort"))

            modifiers = HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=use_preaggregated)
            query = WebOverviewQuery(
                dateRange=DateRange(date_from=date_from, date_to=date_to),
                properties=properties,
                modifiers=modifiers,
            )
            runner = WebOverviewQueryRunner(team=self.team, query=query)
            return runner.calculate()

    def _run_web_stats_table_query(
        self,
        date_from: str,
        date_to: str,
        breakdown: WebStatsBreakdown = WebStatsBreakdown.PAGE,
        cohort_id: int | None = None,
        use_preaggregated: bool = False,
    ):
        with freeze_time(self.QUERY_TIMESTAMP):
            properties = []
            if cohort_id is not None:
                properties.append(CohortPropertyFilter(key="id", value=cohort_id, type="cohort"))

            modifiers = HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=use_preaggregated)
            query = WebStatsTableQuery(
                dateRange=DateRange(date_from=date_from, date_to=date_to),
                properties=properties,
                breakdownBy=breakdown,
                modifiers=modifiers,
            )
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            return runner.calculate()

    def _run_web_goals_query(
        self,
        date_from: str,
        date_to: str,
        cohort_id: int | None = None,
    ):
        with freeze_time(self.QUERY_TIMESTAMP):
            properties = []
            if cohort_id is not None:
                properties.append(CohortPropertyFilter(key="id", value=cohort_id, type="cohort"))

            query = WebGoalsQuery(
                dateRange=DateRange(date_from=date_from, date_to=date_to),
                properties=properties,
            )
            runner = WebGoalsQueryRunner(team=self.team, query=query)
            return runner.calculate()

    def test_web_overview_with_cohort_filter_includes_cohort_member(self):
        s1 = str(uuid7("2026-01-15"))
        s2 = str(uuid7("2026-01-15"))

        self._create_events(
            [
                ("p1_in_cohort", [("2026-01-15", s1, "/page1")]),
                ("p2_not_in_cohort", [("2026-01-15", s2, "/page2")]),
            ]
        )
        flush_persons_and_events()

        cohort = self._create_cohort_with_person("p1_in_cohort")

        response = self._run_web_overview_query("2026-01-15", "2026-01-17", cohort_id=cohort.id)

        visitors = response.results[0]
        assert visitors.key == "visitors"
        assert visitors.value == 1

        views = response.results[1]
        assert views.key == "views"
        assert views.value == 1

    def test_web_overview_without_cohort_filter_includes_all(self):
        s1 = str(uuid7("2026-01-15"))
        s2 = str(uuid7("2026-01-15"))

        self._create_events(
            [
                ("p1_in_cohort", [("2026-01-15", s1, "/page1")]),
                ("p2_not_in_cohort", [("2026-01-15", s2, "/page2")]),
            ]
        )
        flush_persons_and_events()

        response = self._run_web_overview_query("2026-01-15", "2026-01-17")

        visitors = response.results[0]
        assert visitors.key == "visitors"
        assert visitors.value == 2

        views = response.results[1]
        assert views.key == "views"
        assert views.value == 2

    def test_web_overview_cohort_filter_excludes_non_members(self):
        s1 = str(uuid7("2026-01-15"))
        s2 = str(uuid7("2026-01-15"))
        s3 = str(uuid7("2026-01-15"))

        self._create_events(
            [
                ("p1_in_cohort", [("2026-01-15", s1, "/page1"), ("2026-01-15", s1, "/page2")]),
                ("p2_also_in_cohort", [("2026-01-15", s2, "/page1")]),
                (
                    "p3_not_in_cohort",
                    [("2026-01-15", s3, "/page1"), ("2026-01-15", s3, "/page2"), ("2026-01-15", s3, "/page3")],
                ),
            ]
        )
        flush_persons_and_events()

        cohort = Cohort.objects.create(
            team=self.team,
            name="Multi-member Cohort",
            groups=[
                {"properties": [{"key": "name", "value": "p1_in_cohort", "type": "person"}]},
                {"properties": [{"key": "name", "value": "p2_also_in_cohort", "type": "person"}]},
            ],
        )
        cohort.calculate_people_ch(pending_version=0)

        response = self._run_web_overview_query("2026-01-15", "2026-01-17", cohort_id=cohort.id)

        visitors = response.results[0]
        assert visitors.key == "visitors"
        assert visitors.value == 2

        views = response.results[1]
        assert views.key == "views"
        assert views.value == 3

    def test_web_stats_table_with_cohort_filter(self):
        s1 = str(uuid7("2026-01-15"))
        s2 = str(uuid7("2026-01-15"))

        self._create_events(
            [
                ("p1_in_cohort", [("2026-01-15", s1, "/cohort-page")]),
                ("p2_not_in_cohort", [("2026-01-15", s2, "/other-page")]),
            ]
        )
        flush_persons_and_events()

        cohort = self._create_cohort_with_person("p1_in_cohort")

        response = self._run_web_stats_table_query(
            "2026-01-15",
            "2026-01-17",
            breakdown=WebStatsBreakdown.PAGE,
            cohort_id=cohort.id,
        )

        assert len(response.results) == 1
        assert response.results[0][0] == "/cohort-page"

    def test_web_stats_table_without_cohort_filter_includes_all_pages(self):
        s1 = str(uuid7("2026-01-15"))
        s2 = str(uuid7("2026-01-15"))

        self._create_events(
            [
                ("p1_in_cohort", [("2026-01-15", s1, "/cohort-page")]),
                ("p2_not_in_cohort", [("2026-01-15", s2, "/other-page")]),
            ]
        )
        flush_persons_and_events()

        response = self._run_web_stats_table_query(
            "2026-01-15",
            "2026-01-17",
            breakdown=WebStatsBreakdown.PAGE,
        )

        paths = [r[0] for r in response.results]
        assert "/cohort-page" in paths
        assert "/other-page" in paths
        assert len(response.results) == 2

    @parameterized.expand(
        [
            (WebStatsBreakdown.PAGE,),
            (WebStatsBreakdown.BROWSER,),
            (WebStatsBreakdown.DEVICE_TYPE,),
            (WebStatsBreakdown.COUNTRY,),
        ]
    )
    def test_web_stats_table_cohort_filter_works_with_different_breakdowns(self, breakdown: WebStatsBreakdown):
        s1 = str(uuid7("2026-01-15"))
        s2 = str(uuid7("2026-01-15"))

        self._create_events(
            [
                (
                    "p1_in_cohort",
                    [
                        (
                            "2026-01-15",
                            s1,
                            "/page1",
                            {"$browser": "Chrome", "$device_type": "Desktop", "$geoip_country_code": "US"},
                        )
                    ],
                ),
                (
                    "p2_not_in_cohort",
                    [
                        (
                            "2026-01-15",
                            s2,
                            "/page2",
                            {"$browser": "Firefox", "$device_type": "Mobile", "$geoip_country_code": "UK"},
                        )
                    ],
                ),
            ]
        )
        flush_persons_and_events()

        cohort = self._create_cohort_with_person("p1_in_cohort")

        response = self._run_web_stats_table_query(
            "2026-01-15",
            "2026-01-17",
            breakdown=breakdown,
            cohort_id=cohort.id,
        )

        assert len(response.results) == 1

    def test_web_goals_with_cohort_filter(self):
        s1 = str(uuid7("2026-01-15"))
        s2 = str(uuid7("2026-01-15"))

        self._create_events(
            [
                ("p1_in_cohort", [("2026-01-15", s1, "/page1")]),
                ("p2_not_in_cohort", [("2026-01-15", s2, "/page2")]),
            ]
        )
        flush_persons_and_events()

        Action.objects.create(
            team=self.team,
            name="Visit Page 1",
            steps_json=[{"event": "$pageview", "url": "/page1", "url_matching": "contains"}],
        )

        cohort = self._create_cohort_with_person("p1_in_cohort")

        response = self._run_web_goals_query("2026-01-15", "2026-01-17", cohort_id=cohort.id)

        assert response.results is not None
        assert len(response.results) >= 1

    def test_web_overview_cohort_filter_disables_preaggregated_tables(self):
        s1 = str(uuid7("2025-12-01"))

        self._create_events([("p1", [("2025-12-01", s1, "/page1")])])
        flush_persons_and_events()

        cohort = self._create_cohort_with_person("p1")

        with freeze_time(self.QUERY_TIMESTAMP):
            properties = [CohortPropertyFilter(key="id", value=cohort.id, type="cohort")]
            modifiers = HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True)
            query = WebOverviewQuery(
                dateRange=DateRange(date_from="2025-12-01", date_to="2025-12-31"),
                properties=properties,
                modifiers=modifiers,
            )
            runner = WebOverviewQueryRunner(team=self.team, query=query)
            pre_agg_builder = runner.preaggregated_query_builder

            assert not pre_agg_builder.can_use_preaggregated_tables()

    def test_web_stats_table_cohort_filter_disables_preaggregated_tables(self):
        s1 = str(uuid7("2025-12-01"))

        self._create_events([("p1", [("2025-12-01", s1, "/page1")])])
        flush_persons_and_events()

        cohort = self._create_cohort_with_person("p1")

        with freeze_time(self.QUERY_TIMESTAMP):
            properties = [CohortPropertyFilter(key="id", value=cohort.id, type="cohort")]
            modifiers = HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True)
            query = WebStatsTableQuery(
                dateRange=DateRange(date_from="2025-12-01", date_to="2025-12-31"),
                properties=properties,
                breakdownBy=WebStatsBreakdown.PAGE,
                modifiers=modifiers,
            )
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            pre_agg_builder = runner.preaggregated_query_builder

            assert not pre_agg_builder.can_use_preaggregated_tables()

    def test_cohort_filter_with_empty_cohort_returns_no_results(self):
        s1 = str(uuid7("2026-01-15"))

        self._create_events([("p1", [("2026-01-15", s1, "/page1")])])
        flush_persons_and_events()

        empty_cohort = Cohort.objects.create(
            team=self.team,
            name="Empty Cohort",
            groups=[{"properties": [{"key": "name", "value": "nonexistent_person", "type": "person"}]}],
        )
        empty_cohort.calculate_people_ch(pending_version=0)

        response = self._run_web_overview_query("2026-01-15", "2026-01-17", cohort_id=empty_cohort.id)

        visitors = response.results[0]
        assert visitors.key == "visitors"
        assert visitors.value == 0
