from typing import Optional

from freezegun import freeze_time
from parameterized import parameterized

from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.models.utils import uuid7
from posthog.schema import (
    DateRange,
    WebStatsTableQuery,
    WebStatsBreakdown,
    EventPropertyFilter,
    PropertyOperator,
    SessionTableVersion,
    HogQLQueryModifiers,
)
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
            session_id = str(uuid7(person_time))
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
        include_bounce_rate=False,
        include_scroll_depth=False,
        properties=None,
        session_table_version: SessionTableVersion = SessionTableVersion.V1,
        filter_test_accounts: Optional[bool] = False,
    ):
        modifiers = HogQLQueryModifiers(sessionTableVersion=session_table_version)
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            breakdownBy=breakdown_by,
            limit=limit,
            doPathCleaning=bool(path_cleaning_filters),
            includeBounceRate=include_bounce_rate,
            includeScrollDepth=include_scroll_depth,
            filterTestAccounts=filter_test_accounts,
        )
        self.team.path_cleaning_filters = path_cleaning_filters or []
        runner = WebStatsTableQueryRunner(team=self.team, query=query, modifiers=modifiers)
        return runner.calculate()

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_no_crash_when_no_data(self, session_table_version: SessionTableVersion):
        results = self._run_web_stats_table_query(
            "2023-12-08", "2023-12-15", session_table_version=session_table_version
        ).results
        self.assertEqual([], results)

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_increase_in_users(self, session_table_version: SessionTableVersion):
        s1a = str(uuid7("2023-12-02"))
        s1b = str(uuid7("2023-12-13"))
        s2 = str(uuid7("2023-12-10"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1a, "/"), ("2023-12-03", s1a, "/login"), ("2023-12-13", s1b, "/docs")]),
                ("p2", [("2023-12-10", s2, "/")]),
            ]
        )

        results = self._run_web_stats_table_query(
            "2023-12-01", "2023-12-11", session_table_version=session_table_version
        ).results

        self.assertEqual(
            [
                ["/", 2, 2],
                ["/login", 1, 1],
            ],
            results,
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_all_time(self, session_table_version: SessionTableVersion):
        s1a = str(uuid7("2023-12-02"))
        s1b = str(uuid7("2023-12-13"))
        s2 = str(uuid7("2023-12-10"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1a, "/"), ("2023-12-03", s1a, "/login"), ("2023-12-13", s1b, "/docs")]),
                ("p2", [("2023-12-10", s2, "/")]),
            ]
        )

        results = self._run_web_stats_table_query(
            "all", "2023-12-15", session_table_version=session_table_version
        ).results

        self.assertEqual(
            [
                ["/", 2, 2],
                ["/docs", 1, 1],
                ["/login", 1, 1],
            ],
            results,
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_filter_test_accounts(self, session_table_version: SessionTableVersion):
        s1 = str(uuid7("2023-12-02"))
        # Create 1 test account
        self._create_events([("test", [("2023-12-02", s1, "/"), ("2023-12-03", s1, "/login")])])

        results = self._run_web_stats_table_query(
            "2023-12-01", "2023-12-03", session_table_version=session_table_version, filter_test_accounts=True
        ).results

        self.assertEqual(
            [],
            results,
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_dont_filter_test_accounts(self, session_table_version: SessionTableVersion):
        s1 = str(uuid7("2023-12-02"))
        # Create 1 test account
        self._create_events([("test", [("2023-12-02", s1, "/"), ("2023-12-03", s1, "/login")])])

        results = self._run_web_stats_table_query(
            "2023-12-01", "2023-12-03", session_table_version=session_table_version, filter_test_accounts=False
        ).results

        self.assertEqual(
            [["/", 1, 1], ["/login", 1, 1]],
            results,
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_breakdown_channel_type_doesnt_throw(self, session_table_version: SessionTableVersion):
        s1a = str(uuid7("2023-12-02"))
        s1b = str(uuid7("2023-12-13"))
        s2 = str(uuid7("2023-12-10"))
        # not really testing the functionality yet, which is tested elsewhere, just that it runs
        self._create_events(
            [
                ("p1", [("2023-12-02", s1a, "/"), ("2023-12-03", s1a, "/login"), ("2023-12-13", s1b, "/docs")]),
                ("p2", [("2023-12-10", s2, "/")]),
            ]
        )

        results = self._run_web_stats_table_query(
            "2023-12-01",
            "2023-12-03",
            breakdown_by=WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
            session_table_version=session_table_version,
        ).results

        self.assertEqual(
            1,
            len(results),
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_limit(self, session_table_version: SessionTableVersion):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2023-12-10"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1, "/"), ("2023-12-03", s1, "/login")]),
                ("p2", [("2023-12-10", s2, "/")]),
            ]
        )

        response_1 = self._run_web_stats_table_query(
            "all", "2023-12-15", limit=1, session_table_version=session_table_version
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

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_path_filters(self, session_table_version: SessionTableVersion):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2023-12-10"))
        s3 = str(uuid7("2023-12-10"))
        s4 = str(uuid7("2023-12-11"))
        s5 = str(uuid7("2023-12-11"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1, "/cleaned/123/path/456")]),
                ("p2", [("2023-12-10", s2, "/cleaned/123")]),
                ("p3", [("2023-12-10", s3, "/cleaned/456")]),
                ("p4", [("2023-12-11", s4, "/not-cleaned")]),
                ("p5", [("2023-12-11", s5, "/thing_a")]),
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
            session_table_version=session_table_version,
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

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_scroll_depth_bounce_rate_one_user(self, session_table_version: SessionTableVersion):
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
            breakdown_by=WebStatsBreakdown.PAGE,
            include_scroll_depth=True,
            include_bounce_rate=True,
            session_table_version=session_table_version,
        ).results

        self.assertEqual(
            [
                ["/a", 1, 1, 0, 0.1, 0],
                ["/b", 1, 1, None, 0.2, 0],
                ["/c", 1, 1, None, 0.9, 1],
            ],
            results,
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_scroll_depth_bounce_rate(self, session_table_version: SessionTableVersion):
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
            breakdown_by=WebStatsBreakdown.PAGE,
            include_scroll_depth=True,
            include_bounce_rate=True,
            session_table_version=session_table_version,
        ).results

        self.assertEqual(
            [
                ["/a", 3, 4, 1 / 3, 0.5, 0.5],
                ["/b", 2, 2, None, 0.2, 0],
                ["/c", 2, 2, None, 0.9, 1],
            ],
            results,
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_scroll_depth_bounce_rate_with_filter(self, session_table_version: SessionTableVersion):
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
            breakdown_by=WebStatsBreakdown.PAGE,
            include_scroll_depth=True,
            include_bounce_rate=True,
            properties=[EventPropertyFilter(key="$pathname", operator=PropertyOperator.EXACT, value="/a")],
            session_table_version=session_table_version,
        ).results

        self.assertEqual(
            [
                ["/a", 3, 4, 1 / 3, 0.5, 0.5],
            ],
            results,
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_scroll_depth_bounce_rate_path_cleaning(self, session_table_version: SessionTableVersion):
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
            breakdown_by=WebStatsBreakdown.PAGE,
            include_scroll_depth=True,
            include_bounce_rate=True,
            path_cleaning_filters=[
                {"regex": "\\/a\\/\\d+", "alias": "/a/:id"},
                {"regex": "\\/b\\/\\d+", "alias": "/b/:id"},
                {"regex": "\\/c\\/\\d+", "alias": "/c/:id"},
            ],
            session_table_version=session_table_version,
        ).results

        self.assertEqual(
            [
                ["/a/:id", 1, 1, 0, 0.1, 0],
                ["/b/:id", 1, 1, None, 0.2, 0],
                ["/c/:id", 1, 1, None, 0.9, 1],
            ],
            results,
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_bounce_rate_one_user(self, session_table_version: SessionTableVersion):
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
            breakdown_by=WebStatsBreakdown.PAGE,
            include_bounce_rate=True,
            session_table_version=session_table_version,
        ).results

        self.assertEqual(
            [
                ["/a", 1, 1, 0],
                ["/b", 1, 1, None],
                ["/c", 1, 1, None],
            ],
            results,
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_bounce_rate(self, session_table_version: SessionTableVersion):
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
            breakdown_by=WebStatsBreakdown.PAGE,
            include_bounce_rate=True,
            session_table_version=session_table_version,
        ).results

        self.assertEqual(
            [
                ["/a", 3, 4, 1 / 3],
                ["/b", 2, 2, None],
                ["/c", 2, 2, None],
            ],
            results,
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_bounce_rate_with_property(self, session_table_version: SessionTableVersion):
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
            breakdown_by=WebStatsBreakdown.PAGE,
            include_bounce_rate=True,
            properties=[EventPropertyFilter(key="$pathname", operator=PropertyOperator.EXACT, value="/a")],
            session_table_version=session_table_version,
        ).results

        self.assertEqual(
            [
                ["/a", 3, 4, 1 / 3],
            ],
            results,
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_bounce_rate_path_cleaning(self, session_table_version: SessionTableVersion):
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
            breakdown_by=WebStatsBreakdown.PAGE,
            include_bounce_rate=True,
            path_cleaning_filters=[
                {"regex": "\\/a\\/\\d+", "alias": "/a/:id"},
                {"regex": "\\/b\\/\\d+", "alias": "/b/:id"},
                {"regex": "\\/c\\/\\d+", "alias": "/c/:id"},
            ],
            session_table_version=session_table_version,
        ).results

        self.assertEqual(
            [
                ["/a/:id", 1, 1, 0],
                ["/b/:id", 1, 1, None],
                ["/c/:id", 1, 1, None],
            ],
            results,
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_entry_bounce_rate_one_user(self, session_table_version: SessionTableVersion):
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
            breakdown_by=WebStatsBreakdown.INITIAL_PAGE,
            include_bounce_rate=True,
            session_table_version=session_table_version,
        ).results

        self.assertEqual(
            [
                ["/a", 1, 3, 0],
            ],
            results,
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_entry_bounce_rate(self, session_table_version: SessionTableVersion):
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
            breakdown_by=WebStatsBreakdown.INITIAL_PAGE,
            include_bounce_rate=True,
            session_table_version=session_table_version,
        ).results

        self.assertEqual(
            [
                ["/a", 3, 8, 1 / 3],
            ],
            results,
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_entry_bounce_rate_with_property(self, session_table_version: SessionTableVersion):
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
            breakdown_by=WebStatsBreakdown.INITIAL_PAGE,
            include_bounce_rate=True,
            properties=[EventPropertyFilter(key="$pathname", operator=PropertyOperator.EXACT, value="/a")],
            session_table_version=session_table_version,
        ).results

        self.assertEqual(
            [
                ["/a", 3, 4, 1 / 3],
            ],
            results,
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_entry_bounce_rate_path_cleaning(self, session_table_version: SessionTableVersion):
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
            breakdown_by=WebStatsBreakdown.INITIAL_PAGE,
            include_bounce_rate=True,
            path_cleaning_filters=[
                {"regex": "\\/a\\/\\d+", "alias": "/a/:id"},
                {"regex": "\\/b\\/\\d+", "alias": "/b/:id"},
                {"regex": "\\/c\\/\\d+", "alias": "/c/:id"},
            ],
            session_table_version=session_table_version,
        ).results

        self.assertEqual(
            [
                ["/a/:id", 1, 3, 0],
            ],
            results,
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_source_medium_campaign(self, session_table_version: SessionTableVersion):
        d1 = "d1"
        s1 = str(uuid7("2024-06-26"))

        _create_person(
            team_id=self.team.pk,
            distinct_ids=[d1],
            properties={
                "name": d1,
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=d1,
            timestamp="2024-06-26",
            properties={"$session_id": s1, "utm_source": "google", "$referring_domain": "google.com"},
        )

        d2 = "d2"
        s2 = str(uuid7("2024-06-26"))
        _create_person(
            team_id=self.team.pk,
            distinct_ids=[d2],
            properties={
                "name": d2,
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=d2,
            timestamp="2024-06-26",
            properties={"$session_id": s2, "$referring_domain": "news.ycombinator.com", "utm_medium": "referral"},
        )

        results = self._run_web_stats_table_query(
            "all",
            "2024-06-27",
            breakdown_by=WebStatsBreakdown.INITIAL_UTM_SOURCE_MEDIUM_CAMPAIGN,
            session_table_version=session_table_version,
        ).results

        self.assertEqual(
            [["google / (none) / (none)", 1, 1], ["news.ycombinator.com / referral / (none)", 1, 1]],
            results,
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_null_in_utm_tags(self, session_table_version: SessionTableVersion):
        d1 = "d1"
        s1 = str(uuid7("2024-06-26"))

        _create_person(
            team_id=self.team.pk,
            distinct_ids=[d1],
            properties={
                "name": d1,
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=d1,
            timestamp="2024-06-26",
            properties={"$session_id": s1, "utm_source": "google"},
        )

        d2 = "d2"
        s2 = str(uuid7("2024-06-26"))
        _create_person(
            team_id=self.team.pk,
            distinct_ids=[d2],
            properties={
                "name": d2,
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=d2,
            timestamp="2024-06-26",
            properties={
                "$session_id": s2,
            },
        )

        results = self._run_web_stats_table_query(
            "all",
            "2024-06-27",
            breakdown_by=WebStatsBreakdown.INITIAL_UTM_SOURCE,
            session_table_version=session_table_version,
        ).results

        self.assertEqual(
            [["google", 1.0, 1.0], [None, 1.0, 1.0]],
            results,
        )

    @parameterized.expand([[SessionTableVersion.V1], [SessionTableVersion.V2]])
    def test_is_not_set_filter(self, session_table_version: SessionTableVersion):
        d1 = "d1"
        s1 = str(uuid7("2024-06-26"))

        _create_person(
            team_id=self.team.pk,
            distinct_ids=[d1],
            properties={
                "name": d1,
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=d1,
            timestamp="2024-06-26",
            properties={"$session_id": s1, "utm_source": "google"},
        )

        d2 = "d2"
        s2 = str(uuid7("2024-06-26"))
        _create_person(
            team_id=self.team.pk,
            distinct_ids=[d2],
            properties={
                "name": d2,
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=d2,
            timestamp="2024-06-26",
            properties={
                "$session_id": s2,
            },
        )

        results = self._run_web_stats_table_query(
            "all",
            "2024-06-27",
            breakdown_by=WebStatsBreakdown.INITIAL_UTM_SOURCE,
            properties=[EventPropertyFilter(key="utm_source", operator=PropertyOperator.IS_NOT_SET)],
            session_table_version=session_table_version,
        ).results

        self.assertEqual(
            [[None, 1.0, 1.0]],
            results,
        )

    def test_same_user_multiple_sessions(self):
        d1 = "d1"
        s1 = str(uuid7("2024-07-30"))
        s2 = str(uuid7("2024-07-30"))
        _create_person(
            team_id=self.team.pk,
            distinct_ids=[d1],
            properties={
                "name": d1,
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=d1,
            timestamp="2024-07-30",
            properties={"$session_id": s1, "utm_source": "google", "$pathname": "/path"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=d1,
            timestamp="2024-07-30",
            properties={"$session_id": s2, "utm_source": "google", "$pathname": "/path"},
        )

        # Try this with a query that uses session properties
        results_session = self._run_web_stats_table_query(
            "all",
            "2024-07-31",
            breakdown_by=WebStatsBreakdown.INITIAL_UTM_SOURCE,
        ).results
        assert [["google", 1, 2]] == results_session

        # Try this with a query that uses event properties
        results_event = self._run_web_stats_table_query(
            "all",
            "2024-07-31",
            breakdown_by=WebStatsBreakdown.PAGE,
        ).results
        assert [["/path", 1, 2]] == results_event

        # Try this with a query using the bounce rate
        results_event = self._run_web_stats_table_query(
            "all", "2024-07-31", breakdown_by=WebStatsBreakdown.PAGE, include_bounce_rate=True
        ).results
        assert [["/path", 1, 2, None]] == results_event

        # Try this with a query using the scroll depth
        results_event = self._run_web_stats_table_query(
            "all",
            "2024-07-31",
            breakdown_by=WebStatsBreakdown.PAGE,
            include_bounce_rate=True,
            include_scroll_depth=True,
        ).results
        assert [["/path", 1, 2, None, None, None]] == results_event

    def test_no_session_id(self):
        d1 = "d1"
        _create_person(
            team_id=self.team.pk,
            distinct_ids=[d1],
            properties={
                "name": d1,
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=d1,
            timestamp="2024-07-30",
            properties={"utm_source": "google", "$pathname": "/path"},
        )

        # Don't show session property breakdowns type of sessions with no session id
        results = self._run_web_stats_table_query(
            "all",
            "2024-07-31",
            breakdown_by=WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
        ).results
        assert [] == results
        results = self._run_web_stats_table_query(
            "all",
            "2024-07-31",
            breakdown_by=WebStatsBreakdown.INITIAL_PAGE,
        ).results
        assert [] == results

        # Do show event property breakdowns of events of events with no session id
        results = self._run_web_stats_table_query(
            "all",
            "2024-07-31",
            breakdown_by=WebStatsBreakdown.PAGE,
        ).results
        assert [["/path", 1, 1]] == results
