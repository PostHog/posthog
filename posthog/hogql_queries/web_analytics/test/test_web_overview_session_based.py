from freezegun import freeze_time
from posthog.models.utils import uuid7

from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.hogql_queries.web_analytics.web_overview_session_based import WebOverviewSessionBasedQueryRunner
from posthog.schema import WebOverviewQuery, DateRange, HogQLQueryModifiers
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)


@snapshot_clickhouse_queries
class TestWebOverviewSessionBasedQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()

    def _create_events(self, data, event="$pageview"):
        person_result = []
        for user_id, timestamps in data:
            with freeze_time(timestamps[0][0]):
                person_result.append(
                    _create_person(
                        team_id=self.team.pk,
                        distinct_ids=[user_id],
                        properties={"name": user_id},
                    )
                )
            for timestamp, session_id, *extra in timestamps:
                url = extra[0] if extra else "https://example.com"
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=user_id,
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$current_url": url,
                        "$host": "example.com",
                        "$pathname": url.split("?")[0] if url else None,
                    },
                )
        return person_result

    def _run_query(self, date_from, date_to, session_based=False, timezone_conversion=False):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=[],
        )

        modifiers = HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=False,
            convertToProjectTimezone=timezone_conversion,
        )

        runner_class = WebOverviewSessionBasedQueryRunner if session_based else WebOverviewQueryRunner
        runner = runner_class(query=query, team=self.team, modifiers=modifiers)
        return runner.calculate()

    def test_basic_functionality(self):
        session_id = str(uuid7("2023-12-01"))

        self._create_events(
            [
                (
                    "user_1",
                    [
                        ("2023-12-01 10:00:00", session_id, "https://example.com/page1"),
                        ("2023-12-01 10:30:00", session_id, "https://example.com/page2"),
                    ],
                ),
            ]
        )

        regular_response = self._run_query("2023-12-01", "2023-12-01")
        session_response = self._run_query("2023-12-01", "2023-12-01", session_based=True)

        regular_metrics = {item.key: item.value for item in regular_response.results}
        session_metrics = {item.key: item.value for item in session_response.results}

        self.assertEqual(regular_metrics["views"], 2)
        self.assertEqual(session_metrics["views"], 2)
        self.assertEqual(regular_metrics["visitors"], 1)
        self.assertEqual(session_metrics["visitors"], 1)

    def test_cross_day_session_filtering_difference(self):
        session_id = str(uuid7("2023-12-02"))

        self._create_events(
            [
                (
                    "user_1",
                    [
                        ("2023-12-02 10:00:00", session_id, "https://example.com/page1"),
                        ("2023-12-02 10:30:00", session_id, "https://example.com/page2"),
                        ("2023-12-03 09:00:00", session_id, "https://example.com/page3"),
                    ],
                )
            ]
        )

        regular_response = self._run_query("2023-12-02", "2023-12-02")
        session_response = self._run_query("2023-12-02", "2023-12-02", session_based=True)

        regular_metrics = {item.key: item.value for item in regular_response.results}
        session_metrics = {item.key: item.value for item in session_response.results}

        self.assertEqual(regular_metrics["views"], 2)
        self.assertEqual(session_metrics["views"], 3)
        self.assertEqual(regular_metrics["visitors"], 1)
        self.assertEqual(session_metrics["visitors"], 1)

    def test_session_outside_range(self):
        session_id = str(uuid7("2023-12-01"))

        self._create_events(
            [
                (
                    "user_1",
                    [
                        ("2023-12-01 10:00:00", session_id, "https://example.com/page1"),
                        ("2023-12-01 10:30:00", session_id, "https://example.com/page2"),
                        ("2023-12-02 09:00:00", session_id, "https://example.com/page3"),
                    ],
                )
            ]
        )

        regular_response = self._run_query("2023-12-02", "2023-12-02")
        session_response = self._run_query("2023-12-02", "2023-12-02", session_based=True)

        regular_metrics = {item.key: item.value for item in regular_response.results}
        session_metrics = {item.key: item.value for item in session_response.results}

        self.assertEqual(regular_metrics["views"], 0)
        self.assertEqual(session_metrics["views"], 0)
        self.assertEqual(regular_metrics["visitors"], 0)
        self.assertEqual(session_metrics["visitors"], 0)

    def test_timezone_conversion_respected(self):
        self.team.timezone = "America/New_York"
        self.team.save()

        session_id = str(uuid7("2023-12-01"))

        self._create_events(
            [
                (
                    "user_1",
                    [
                        ("2023-12-01 10:00:00", session_id, "https://example.com/page1"),
                        ("2023-12-01 10:30:00", session_id, "https://example.com/page2"),
                    ],
                ),
            ]
        )

        utc_response = self._run_query("2023-12-01", "2023-12-01", session_based=True, timezone_conversion=False)
        tz_response = self._run_query("2023-12-01", "2023-12-01", session_based=True, timezone_conversion=True)

        utc_metrics = {item.key: item.value for item in utc_response.results}
        tz_metrics = {item.key: item.value for item in tz_response.results}

        self.assertEqual(utc_metrics["views"], 2)
        self.assertEqual(tz_metrics["views"], 2)

    def test_conversion_goal_not_supported(self):
        from posthog.schema import CustomEventConversionGoal

        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-01"),
            properties=[],
            conversionGoal=CustomEventConversionGoal(customEventName="test_event"),
        )

        modifiers = HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=False,
            convertToProjectTimezone=False,
        )

        runner = WebOverviewSessionBasedQueryRunner(query=query, team=self.team, modifiers=modifiers)

        with self.assertRaises(NotImplementedError):
            runner.calculate()

    def test_revenue_not_supported(self):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-01"), properties=[], includeRevenue=True
        )

        modifiers = HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=False,
            convertToProjectTimezone=False,
        )

        runner = WebOverviewSessionBasedQueryRunner(query=query, team=self.team, modifiers=modifiers)

        with self.assertRaises(NotImplementedError):
            runner.calculate()

    def test_matches_preaggregated_logic(self):
        session_id = str(uuid7("2023-12-01"))

        self._create_events(
            [
                (
                    "user_1",
                    [
                        ("2023-12-01 10:00:00", session_id, "https://example.com/home"),
                        ("2023-12-01 10:30:00", session_id, "https://example.com/about"),
                        ("2023-12-02 09:00:00", session_id, "https://example.com/contact"),
                    ],
                )
            ]
        )

        dec1_response = self._run_query("2023-12-01", "2023-12-01", session_based=True)
        dec2_response = self._run_query("2023-12-02", "2023-12-02", session_based=True)

        dec1_metrics = {item.key: item.value for item in dec1_response.results}
        dec2_metrics = {item.key: item.value for item in dec2_response.results}

        self.assertEqual(dec1_metrics["views"], 3)
        self.assertEqual(dec1_metrics["visitors"], 1)
        self.assertEqual(dec2_metrics["views"], 0)
        self.assertEqual(dec2_metrics["visitors"], 0)
