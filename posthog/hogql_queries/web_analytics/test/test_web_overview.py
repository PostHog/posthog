from typing import Optional
from unittest.mock import MagicMock, patch
from freezegun import freeze_time
from parameterized import parameterized

from posthog.clickhouse.client.execute import sync_execute
from posthog.hogql.constants import LimitContext
from posthog.hogql.query import INCREASED_MAX_EXECUTION_TIME
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.schema import WebOverviewQuery, DateRange
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
)


class TestWebOverviewQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _create_events(self, data, event="$pageview"):
        person_result = []
        for id, timestamps in data:
            with freeze_time(timestamps[0][0]):
                person_result.append(
                    _create_person(
                        team_id=self.team.pk,
                        distinct_ids=[id],
                        properties={
                            "name": id,
                            **({"email": "test@posthog.com"} if id == "test" else {}),
                        },
                    )
                )
            for timestamp, session_id in timestamps:
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=id,
                    timestamp=timestamp,
                    properties={"$session_id": session_id},
                )
        return person_result

    def _run_web_overview_query(
        self,
        date_from: str,
        date_to: str,
        use_sessions_table: bool = False,
        compare: bool = True,
        limit_context: Optional[LimitContext] = None,
    ):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=[],
            compare=compare,
            useSessionsTable=use_sessions_table,
        )
        runner = WebOverviewQueryRunner(team=self.team, query=query, limit_context=limit_context)
        return runner.calculate()

    @parameterized.expand([(True,), (False,)])
    def test_no_crash_when_no_data(self, use_sessions_table):
        results = self._run_web_overview_query(
            "2023-12-08", "2023-12-15", use_sessions_table=use_sessions_table
        ).results
        self.assertEqual(5, len(results))

    @parameterized.expand([(True,), (False,)])
    def test_increase_in_users(self, use_sessions_table):
        self._create_events(
            [
                ("p1", [("2023-12-02", "s1a"), ("2023-12-03", "s1a"), ("2023-12-12", "s1b")]),
                ("p2", [("2023-12-11", "s2")]),
            ]
        )

        results = self._run_web_overview_query(
            "2023-12-08", "2023-12-15", use_sessions_table=use_sessions_table
        ).results

        visitors = results[0]
        self.assertEqual("visitors", visitors.key)
        self.assertEqual(2, visitors.value)
        self.assertEqual(1, visitors.previous)
        self.assertEqual(100, visitors.changeFromPreviousPct)

        views = results[1]
        self.assertEqual("views", views.key)
        self.assertEqual(2, views.value)
        self.assertEqual(2, views.previous)
        self.assertEqual(0, views.changeFromPreviousPct)

        sessions = results[2]
        self.assertEqual("sessions", sessions.key)
        self.assertEqual(2, sessions.value)
        self.assertEqual(1, sessions.previous)
        self.assertEqual(100, sessions.changeFromPreviousPct)

        duration_s = results[3]
        self.assertEqual("session duration", duration_s.key)
        self.assertEqual(0, duration_s.value)
        self.assertEqual(60 * 60 * 24, duration_s.previous)
        self.assertEqual(-100, duration_s.changeFromPreviousPct)

        bounce = results[4]
        self.assertEqual("bounce rate", bounce.key)
        self.assertEqual(100, bounce.value)
        self.assertEqual(0, bounce.previous)
        self.assertEqual(None, bounce.changeFromPreviousPct)

    @parameterized.expand([(True,), (False,)])
    def test_all_time(self, use_sessions_table):
        self._create_events(
            [
                ("p1", [("2023-12-02", "s1a"), ("2023-12-03", "s1a"), ("2023-12-12", "s1b")]),
                ("p2", [("2023-12-11", "s2")]),
            ]
        )

        results = self._run_web_overview_query(
            "all", "2023-12-15", compare=False, use_sessions_table=use_sessions_table
        ).results

        visitors = results[0]
        self.assertEqual("visitors", visitors.key)
        self.assertEqual(2, visitors.value)
        self.assertEqual(None, visitors.previous)
        self.assertEqual(None, visitors.changeFromPreviousPct)

        views = results[1]
        self.assertEqual("views", views.key)
        self.assertEqual(4, views.value)
        self.assertEqual(None, views.previous)
        self.assertEqual(None, views.changeFromPreviousPct)

        sessions = results[2]
        self.assertEqual("sessions", sessions.key)
        self.assertEqual(3, sessions.value)
        self.assertEqual(None, sessions.previous)
        self.assertEqual(None, sessions.changeFromPreviousPct)

        duration_s = results[3]
        self.assertEqual("session duration", duration_s.key)
        self.assertEqual(60 * 60 * 24 / 3, duration_s.value)
        self.assertEqual(None, duration_s.previous)
        self.assertEqual(None, duration_s.changeFromPreviousPct)

        bounce = results[4]
        self.assertEqual("bounce rate", bounce.key)
        self.assertAlmostEqual(100 * 2 / 3, bounce.value)
        self.assertEqual(None, bounce.previous)
        self.assertEqual(None, bounce.changeFromPreviousPct)

    @parameterized.expand([(True,), (False,)])
    def test_filter_test_accounts(self, use_sessions_table):
        # Create 1 test account
        self._create_events([("test", [("2023-12-02", "s1"), ("2023-12-03", "s1")])])

        results = self._run_web_overview_query(
            "2023-12-01", "2023-12-03", use_sessions_table=use_sessions_table
        ).results

        visitors = results[0]
        self.assertEqual(0, visitors.value)

        views = results[1]
        self.assertEqual(0, views.value)

        sessions = results[2]
        self.assertEqual(0, sessions.value)

        duration_s = results[3]
        self.assertEqual(None, duration_s.value)

        bounce = results[4]
        self.assertEqual("bounce rate", bounce.key)
        self.assertEqual(None, bounce.value)

    @parameterized.expand([(True,), (False,)])
    def test_correctly_counts_pageviews_in_long_running_session(self, use_sessions_table):
        # this test is important when using the sessions table as the raw sessions table will have 3 entries, one per day
        self._create_events(
            [
                ("p1", [("2023-12-01", "s1"), ("2023-12-02", "s1"), ("2023-12-03", "s1")]),
            ]
        )

        results = self._run_web_overview_query(
            "2023-12-01", "2023-12-03", use_sessions_table=use_sessions_table
        ).results

        visitors = results[0]
        self.assertEqual(1, visitors.value)

        views = results[1]
        self.assertEqual(3, views.value)

        sessions = results[2]
        self.assertEqual(1, sessions.value)

    @patch("posthog.hogql.query.sync_execute", wraps=sync_execute)
    def test_limit_is_context_aware(self, mock_sync_execute: MagicMock):
        self._run_web_overview_query("2023-12-01", "2023-12-03", limit_context=LimitContext.QUERY_ASYNC)

        mock_sync_execute.assert_called_once()
        self.assertIn(f" max_execution_time={INCREASED_MAX_EXECUTION_TIME},", mock_sync_execute.call_args[0][0])
