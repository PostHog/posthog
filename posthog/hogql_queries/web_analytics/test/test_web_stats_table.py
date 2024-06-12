import uuid
from typing import Union

from freezegun import freeze_time
from parameterized import parameterized

from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.hogql_queries.web_analytics.stats_table_legacy import LegacyWebStatsTableQueryRunner
from posthog.schema import DateRange, WebStatsTableQuery, WebStatsBreakdown, EventPropertyFilter, PropertyOperator
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

    def _create_pageviews(self, distinct_id: str, list_path_time_scroll: list[tuple[str, str, float]]):
        person_time = list_path_time_scroll[0][1]
        with freeze_time(person_time):
            person_result = _create_person(
                team_id=self.team.pk,
                distinct_ids=[distinct_id],
                properties={
                    "name": distinct_id,
                    **({"email": "test@posthog.com"} if distinct_id == "test" else {}),
                },
            )
            session_id = str(uuid.uuid4())
            prev_path_time_scroll = None
            for path_time_scroll in list_path_time_scroll:
                pathname, time, scroll = path_time_scroll
                prev_pathname, _, prev_scroll = prev_path_time_scroll or (None, None, None)
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=distinct_id,
                    timestamp=time,
                    properties={
                        "$session_id": session_id,
                        "$pathname": pathname,
                        "$current_url": "http://www.example.com" + pathname,
                        "$prev_pageview_pathname": prev_pathname,
                        "$prev_pageview_max_scroll_percentage": prev_scroll,
                        "$prev_pageview_max_content_percentage": prev_scroll,
                    },
                )
                prev_path_time_scroll = path_time_scroll
            if prev_path_time_scroll:
                prev_pathname, _, prev_scroll = prev_path_time_scroll
                _create_event(
                    team=self.team,
                    event="$pageleave",
                    distinct_id=distinct_id,
                    timestamp=prev_path_time_scroll[1],
                    properties={
                        "$session_id": session_id,
                        "$pathname": prev_pathname,
                        "$current_url": "http://www.example.com" + pathname,
                        "$prev_pageview_pathname": prev_pathname,
                        "$prev_pageview_max_scroll_percentage": prev_scroll,
                        "$prev_pageview_max_content_percentage": prev_scroll,
                    },
                )
        return person_result

    def _run_web_stats_table_query(
        self,
        date_from,
        date_to,
        breakdown_by=WebStatsBreakdown.PAGE,
        limit=None,
        path_cleaning_filters=None,
        use_sessions_table=True,
        include_bounce_rate=False,
        include_scroll_depth=False,
        properties=None,
    ):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            breakdownBy=breakdown_by,
            limit=limit,
            doPathCleaning=bool(path_cleaning_filters),
            includeBounceRate=include_bounce_rate,
            includeScrollDepth=include_scroll_depth,
        )
        self.team.path_cleaning_filters = path_cleaning_filters or []
        if use_sessions_table:
            runner: Union[WebStatsTableQueryRunner, LegacyWebStatsTableQueryRunner] = WebStatsTableQueryRunner(
                team=self.team, query=query
            )
        else:
            runner = LegacyWebStatsTableQueryRunner(team=self.team, query=query)
        return runner.calculate()

    @parameterized.expand([(True,), (False,)])
    def test_no_crash_when_no_data(self, use_sessions_table):
        results = self._run_web_stats_table_query(
            "2023-12-08", "2023-12-15", use_sessions_table=use_sessions_table
        ).results
        self.assertEqual([], results)

    @parameterized.expand([(True,), (False,)])
    def test_increase_in_users(self, use_sessions_table):
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

    @parameterized.expand([(True,), (False,)])
    def test_all_time(self, use_sessions_table):
        self._create_events(
            [
                ("p1", [("2023-12-02", "s1a", "/"), ("2023-12-03", "s1a", "/login"), ("2023-12-13", "s1b", "/docs")]),
                ("p2", [("2023-12-10", "s2", "/")]),
            ]
        )

        results = self._run_web_stats_table_query("all", "2023-12-15", use_sessions_table=use_sessions_table).results

        self.assertEqual(
            [
                ["/", 2, 2],
                ["/docs", 1, 1],
                ["/login", 1, 1],
            ],
            results,
        )

    @parameterized.expand([(True,), (False,)])
    def test_filter_test_accounts(self, use_sessions_table):
        # Create 1 test account
        self._create_events([("test", [("2023-12-02", "s1", "/"), ("2023-12-03", "s1", "/login")])])

        results = self._run_web_stats_table_query(
            "2023-12-01", "2023-12-03", use_sessions_table=use_sessions_table
        ).results

        self.assertEqual(
            [],
            results,
        )

    @parameterized.expand([(True,), (False,)])
    def test_breakdown_channel_type_doesnt_throw(self, use_sessions_table):
        # not really testing the functionality yet, which is tested elsewhere, just that it runs
        self._create_events(
            [
                ("p1", [("2023-12-02", "s1a", "/"), ("2023-12-03", "s1a", "/login"), ("2023-12-13", "s1b", "/docs")]),
                ("p2", [("2023-12-10", "s2", "/")]),
            ]
        )

        results = self._run_web_stats_table_query(
            "2023-12-01",
            "2023-12-03",
            breakdown_by=WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
            use_sessions_table=use_sessions_table,
        ).results

        self.assertEqual(
            1,
            len(results),
        )

    @parameterized.expand([(True,), (False,)])
    def test_limit(self, use_sessions_table):
        self._create_events(
            [
                ("p1", [("2023-12-02", "s1", "/"), ("2023-12-03", "s1", "/login")]),
                ("p2", [("2023-12-10", "s2", "/")]),
            ]
        )

        response_1 = self._run_web_stats_table_query(
            "all", "2023-12-15", limit=1, use_sessions_table=use_sessions_table
        )
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

    @parameterized.expand([(True,), (False,)])
    def test_path_filters(self, use_sessions_table):
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
            use_sessions_table=use_sessions_table,
        ).results

        self.assertEqual(
            [
                ["/cleaned/:id", 2, 2],
                ["/cleaned/:id/path/:id", 1, 1],
                ["/not-cleaned", 1, 1],
                ["/thing_c", 1, 1],
            ],
            results,
        )

    def test_scroll_depth_bounce_rate_one_user(self):
        self._create_pageviews(
            "p1",
            [
                ("/a", "2023-12-02T12:00:00", 0.1),
                ("/b", "2023-12-02T12:00:01", 0.2),
                ("/c", "2023-12-02T12:00:02", 0.9),
            ],
        )

        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            use_sessions_table=True,
            breakdown_by=WebStatsBreakdown.PAGE,
            include_scroll_depth=True,
            include_bounce_rate=True,
        ).results

        self.assertEqual(
            [
                ["/a", 1, 1, 0, 0.1, 0],
                ["/b", 1, 1, None, 0.2, 0],
                ["/c", 1, 1, None, 0.9, 1],
            ],
            results,
        )

    def test_scroll_depth_bounce_rate(self):
        self._create_pageviews(
            "p1",
            [
                ("/a", "2023-12-02T12:00:00", 0.1),
                ("/b", "2023-12-02T12:00:01", 0.2),
                ("/c", "2023-12-02T12:00:02", 0.9),
            ],
        )
        self._create_pageviews(
            "p2",
            [
                ("/a", "2023-12-02T12:00:00", 0.9),
                ("/a", "2023-12-02T12:00:01", 0.9),
                ("/b", "2023-12-02T12:00:02", 0.2),
                ("/c", "2023-12-02T12:00:03", 0.9),
            ],
        )
        self._create_pageviews(
            "p3",
            [
                ("/a", "2023-12-02T12:00:00", 0.1),
            ],
        )

        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            use_sessions_table=True,
            breakdown_by=WebStatsBreakdown.PAGE,
            include_scroll_depth=True,
            include_bounce_rate=True,
        ).results

        self.assertEqual(
            [
                ["/a", 3, 4, 1 / 3, 0.5, 0.5],
                ["/b", 2, 2, None, 0.2, 0],
                ["/c", 2, 2, None, 0.9, 1],
            ],
            results,
        )

    def test_scroll_depth_bounce_rate_with_filter(self):
        self._create_pageviews(
            "p1",
            [
                ("/a", "2023-12-02T12:00:00", 0.1),
                ("/b", "2023-12-02T12:00:01", 0.2),
                ("/c", "2023-12-02T12:00:02", 0.9),
            ],
        )
        self._create_pageviews(
            "p2",
            [
                ("/a", "2023-12-02T12:00:00", 0.9),
                ("/a", "2023-12-02T12:00:01", 0.9),
                ("/b", "2023-12-02T12:00:02", 0.2),
                ("/c", "2023-12-02T12:00:03", 0.9),
            ],
        )
        self._create_pageviews(
            "p3",
            [
                ("/a", "2023-12-02T12:00:00", 0.1),
            ],
        )

        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            use_sessions_table=True,
            breakdown_by=WebStatsBreakdown.PAGE,
            include_scroll_depth=True,
            include_bounce_rate=True,
            properties=[EventPropertyFilter(key="$pathname", operator=PropertyOperator.EXACT, value="/a")],
        ).results

        self.assertEqual(
            [
                ["/a", 3, 4, 1 / 3, 0.5, 0.5],
            ],
            results,
        )

    def test_scroll_depth_bounce_rate_path_cleaning(self):
        self._create_pageviews(
            "p1",
            [
                ("/a/123", "2023-12-02T12:00:00", 0.1),
                ("/b/123", "2023-12-02T12:00:01", 0.2),
                ("/c/123", "2023-12-02T12:00:02", 0.9),
            ],
        )

        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            use_sessions_table=True,
            breakdown_by=WebStatsBreakdown.PAGE,
            include_scroll_depth=True,
            include_bounce_rate=True,
            path_cleaning_filters=[
                {"regex": "\\/a\\/\\d+", "alias": "/a/:id"},
                {"regex": "\\/b\\/\\d+", "alias": "/b/:id"},
                {"regex": "\\/c\\/\\d+", "alias": "/c/:id"},
            ],
        ).results

        self.assertEqual(
            [
                ["/a/:id", 1, 1, 0, 0.1, 0],
                ["/b/:id", 1, 1, None, 0.2, 0],
                ["/c/:id", 1, 1, None, 0.9, 1],
            ],
            results,
        )

    def test_bounce_rate_one_user(self):
        self._create_pageviews(
            "p1",
            [
                ("/a", "2023-12-02T12:00:00", 0.1),
                ("/b", "2023-12-02T12:00:01", 0.2),
                ("/c", "2023-12-02T12:00:02", 0.9),
            ],
        )

        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            use_sessions_table=True,
            breakdown_by=WebStatsBreakdown.PAGE,
            include_bounce_rate=True,
        ).results

        self.assertEqual(
            [
                ["/a", 1, 1, 0],
                ["/b", 1, 1, None],
                ["/c", 1, 1, None],
            ],
            results,
        )

    def test_bounce_rate(self):
        self._create_pageviews(
            "p1",
            [
                ("/a", "2023-12-02T12:00:00", 0.1),
                ("/b", "2023-12-02T12:00:01", 0.2),
                ("/c", "2023-12-02T12:00:02", 0.9),
            ],
        )
        self._create_pageviews(
            "p2",
            [
                ("/a", "2023-12-02T12:00:00", 0.9),
                ("/a", "2023-12-02T12:00:01", 0.9),
                ("/b", "2023-12-02T12:00:02", 0.2),
                ("/c", "2023-12-02T12:00:03", 0.9),
            ],
        )
        self._create_pageviews(
            "p3",
            [
                ("/a", "2023-12-02T12:00:00", 0.1),
            ],
        )

        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            use_sessions_table=True,
            breakdown_by=WebStatsBreakdown.PAGE,
            include_bounce_rate=True,
        ).results

        self.assertEqual(
            [
                ["/a", 3, 4, 1 / 3],
                ["/b", 2, 2, None],
                ["/c", 2, 2, None],
            ],
            results,
        )

    def test_bounce_rate_with_property(self):
        self._create_pageviews(
            "p1",
            [
                ("/a", "2023-12-02T12:00:00", 0.1),
                ("/b", "2023-12-02T12:00:01", 0.2),
                ("/c", "2023-12-02T12:00:02", 0.9),
            ],
        )
        self._create_pageviews(
            "p2",
            [
                ("/a", "2023-12-02T12:00:00", 0.9),
                ("/a", "2023-12-02T12:00:01", 0.9),
                ("/b", "2023-12-02T12:00:02", 0.2),
                ("/c", "2023-12-02T12:00:03", 0.9),
            ],
        )
        self._create_pageviews(
            "p3",
            [
                ("/a", "2023-12-02T12:00:00", 0.1),
            ],
        )

        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            use_sessions_table=True,
            breakdown_by=WebStatsBreakdown.PAGE,
            include_bounce_rate=True,
            properties=[EventPropertyFilter(key="$pathname", operator=PropertyOperator.EXACT, value="/a")],
        ).results

        self.assertEqual(
            [
                ["/a", 3, 4, 1 / 3],
            ],
            results,
        )

    def test_bounce_rate_path_cleaning(self):
        self._create_pageviews(
            "p1",
            [
                ("/a/123", "2023-12-02T12:00:00", 0.1),
                ("/b/123", "2023-12-02T12:00:01", 0.2),
                ("/c/123", "2023-12-02T12:00:02", 0.9),
            ],
        )

        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            use_sessions_table=True,
            breakdown_by=WebStatsBreakdown.PAGE,
            include_bounce_rate=True,
            path_cleaning_filters=[
                {"regex": "\\/a\\/\\d+", "alias": "/a/:id"},
                {"regex": "\\/b\\/\\d+", "alias": "/b/:id"},
                {"regex": "\\/c\\/\\d+", "alias": "/c/:id"},
            ],
        ).results

        self.assertEqual(
            [
                ["/a/:id", 1, 1, 0],
                ["/b/:id", 1, 1, None],
                ["/c/:id", 1, 1, None],
            ],
            results,
        )

    def test_entry_bounce_rate_one_user(self):
        self._create_pageviews(
            "p1",
            [
                ("/a", "2023-12-02T12:00:00", 0.1),
                ("/b", "2023-12-02T12:00:01", 0.2),
                ("/c", "2023-12-02T12:00:02", 0.9),
            ],
        )

        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            use_sessions_table=True,
            breakdown_by=WebStatsBreakdown.INITIAL_PAGE,
            include_bounce_rate=True,
        ).results

        self.assertEqual(
            [
                ["/a", 1, 3, 0],
            ],
            results,
        )

    def test_entry_bounce_rate(self):
        self._create_pageviews(
            "p1",
            [
                ("/a", "2023-12-02T12:00:00", 0.1),
                ("/b", "2023-12-02T12:00:01", 0.2),
                ("/c", "2023-12-02T12:00:02", 0.9),
            ],
        )
        self._create_pageviews(
            "p2",
            [
                ("/a", "2023-12-02T12:00:00", 0.9),
                ("/a", "2023-12-02T12:00:01", 0.9),
                ("/b", "2023-12-02T12:00:02", 0.2),
                ("/c", "2023-12-02T12:00:03", 0.9),
            ],
        )
        self._create_pageviews(
            "p3",
            [
                ("/a", "2023-12-02T12:00:00", 0.1),
            ],
        )

        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            use_sessions_table=True,
            breakdown_by=WebStatsBreakdown.INITIAL_PAGE,
            include_bounce_rate=True,
        ).results

        self.assertEqual(
            [
                ["/a", 3, 8, 1 / 3],
            ],
            results,
        )

    def test_entry_bounce_rate_with_property(self):
        self._create_pageviews(
            "p1",
            [
                ("/a", "2023-12-02T12:00:00", 0.1),
                ("/b", "2023-12-02T12:00:01", 0.2),
                ("/c", "2023-12-02T12:00:02", 0.9),
            ],
        )
        self._create_pageviews(
            "p2",
            [
                ("/a", "2023-12-02T12:00:00", 0.9),
                ("/a", "2023-12-02T12:00:01", 0.9),
                ("/b", "2023-12-02T12:00:02", 0.2),
                ("/c", "2023-12-02T12:00:03", 0.9),
            ],
        )
        self._create_pageviews(
            "p3",
            [
                ("/a", "2023-12-02T12:00:00", 0.1),
            ],
        )

        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            use_sessions_table=True,
            breakdown_by=WebStatsBreakdown.INITIAL_PAGE,
            include_bounce_rate=True,
            properties=[EventPropertyFilter(key="$pathname", operator=PropertyOperator.EXACT, value="/a")],
        ).results

        self.assertEqual(
            [
                ["/a", 3, 4, 1 / 3],
            ],
            results,
        )

    def test_entry_bounce_rate_path_cleaning(self):
        self._create_pageviews(
            "p1",
            [
                ("/a/123", "2023-12-02T12:00:00", 0.1),
                ("/b/123", "2023-12-02T12:00:01", 0.2),
                ("/c/123", "2023-12-02T12:00:02", 0.9),
            ],
        )

        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            use_sessions_table=True,
            breakdown_by=WebStatsBreakdown.INITIAL_PAGE,
            include_bounce_rate=True,
            path_cleaning_filters=[
                {"regex": "\\/a\\/\\d+", "alias": "/a/:id"},
                {"regex": "\\/b\\/\\d+", "alias": "/b/:id"},
                {"regex": "\\/c\\/\\d+", "alias": "/c/:id"},
            ],
        ).results

        self.assertEqual(
            [
                ["/a/:id", 1, 3, 0],
            ],
            results,
        )
