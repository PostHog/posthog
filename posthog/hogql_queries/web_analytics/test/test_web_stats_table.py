from freezegun import freeze_time

from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.schema import DateRange, WebStatsTableQuery, WebStatsBreakdown
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
)


class TestWebStatsTableQueryRunner(ClickhouseTestMixin, APIBaseTest):
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
            for timestamp, session_id, pathname in timestamps:
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=id,
                    timestamp=timestamp,
                    properties={"$session_id": session_id, "$pathname": pathname},
                )
        return person_result

    def _run_web_stats_table_query(self, date_from, date_to, breakdown_by=WebStatsBreakdown.Page):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to), properties=[], breakdownBy=breakdown_by
        )
        runner = WebStatsTableQueryRunner(team=self.team, query=query)
        return runner.calculate()

    def test_no_crash_when_no_data(self):
        results = self._run_web_stats_table_query("2023-12-08", "2023-12-15").results
        self.assertEqual([], results)

    def test_increase_in_users(self):
        self._create_events(
            [
                ("p1", [("2023-12-02", "s1a", "/"), ("2023-12-03", "s1a", "/login"), ("2023-12-13", "s1b", "/docs")]),
                ("p2", [("2023-12-10", "s2", "/")]),
            ]
        )

        results = self._run_web_stats_table_query("2023-12-01", "2023-12-11").results

        self.assertEqual(
            [
                ("/", 2, 2, 0),
                ("/login", 1, 1, 0),
            ],
            results,
        )

    def test_all_time(self):
        self._create_events(
            [
                ("p1", [("2023-12-02", "s1a", "/"), ("2023-12-03", "s1a", "/login"), ("2023-12-13", "s1b", "/docs")]),
                ("p2", [("2023-12-10", "s2", "/")]),
            ]
        )

        results = self._run_web_stats_table_query("all", "2023-12-15").results

        self.assertEqual(
            [
                ("/", 2, 2, 0),
                ("/login", 1, 1, 0),
                ("/docs", 1, 1, 0),
            ],
            results,
        )

    def test_filter_test_accounts(self):
        # Create 1 test account
        self._create_events([("test", [("2023-12-02", "s1", "/"), ("2023-12-03", "s1", "/login")])])

        results = self._run_web_stats_table_query("2023-12-01", "2023-12-03").results

        self.assertEqual(
            [],
            results,
        )

    def test_breakdown_channel_type_doesnt_throw(self):
        # not really testing the functionality yet, which is tested elsewhere, just that it runs
        self._create_events(
            [
                ("p1", [("2023-12-02", "s1a", "/"), ("2023-12-03", "s1a", "/login"), ("2023-12-13", "s1b", "/docs")]),
                ("p2", [("2023-12-10", "s2", "/")]),
            ]
        )

        results = self._run_web_stats_table_query(
            "2023-12-01", "2023-12-03", breakdown_by=WebStatsBreakdown.InitialChannelType
        ).results

        self.assertEqual(
            1,
            len(results),
        )
