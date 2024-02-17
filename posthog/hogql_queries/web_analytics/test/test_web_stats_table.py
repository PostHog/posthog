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

    def _run_web_stats_table_query(
        self, date_from, date_to, breakdown_by=WebStatsBreakdown.Page, limit=None, path_cleaning_filters=None
    ):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=[],
            breakdownBy=breakdown_by,
            limit=limit,
            doPathCleaning=bool(path_cleaning_filters),
        )
        self.team.path_cleaning_filters = path_cleaning_filters or []
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
                ["/", 2, 2],
                ["/login", 1, 1],
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
                ["/", 2, 2],
                ["/login", 1, 1],
                ["/docs", 1, 1],
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

    def test_limit(self):
        self._create_events(
            [
                ("p1", [("2023-12-02", "s1", "/"), ("2023-12-03", "s1", "/login")]),
                ("p2", [("2023-12-10", "s2", "/")]),
            ]
        )

        response_1 = self._run_web_stats_table_query("all", "2023-12-15", limit=1)
        self.assertEqual(
            [
                ["/", 2, 2],
            ],
            response_1.results,
        )
        self.assertEqual(True, response_1.hasMore)

        response_2 = self._run_web_stats_table_query("all", "2023-12-15", limit=2)
        self.assertEqual(
            [
                ["/", 2, 2],
                ["/login", 1, 1],
            ],
            response_2.results,
        )
        self.assertEqual(False, response_2.hasMore)

    def test_path_filters(self):
        self._create_events(
            [
                ("p1", [("2023-12-02", "s1", "/cleaned/123/path/456")]),
                ("p2", [("2023-12-10", "s2", "/cleaned/123")]),
                ("p3", [("2023-12-10", "s3", "/cleaned/456")]),
                ("p4", [("2023-12-11", "s4", "/not-cleaned")]),
                ("p5", [("2023-12-11", "s5", "/thing_a")]),
            ]
        )

        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            path_cleaning_filters=[
                {"regex": "\\/cleaned\\/\\d+", "alias": "/cleaned/:id"},
                {"regex": "\\/path\\/\\d+", "alias": "/path/:id"},
                {"regex": "thing_a", "alias": "thing_b"},
                {"regex": "thing_b", "alias": "thing_c"},
            ],
        ).results

        self.assertEqual(
            [
                ["/cleaned/:id", 2, 2],
                ["/thing_c", 1, 1],
                ["/not-cleaned", 1, 1],
                ["/cleaned/:id/path/:id", 1, 1],
            ],
            results,
        )
