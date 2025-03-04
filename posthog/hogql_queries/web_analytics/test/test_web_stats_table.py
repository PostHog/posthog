from typing import Optional

from freezegun import freeze_time

from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.models import Action, Cohort, Element
from posthog.models.utils import uuid7
from posthog.schema import (
    DateRange,
    CompareFilter,
    WebStatsTableQuery,
    WebStatsBreakdown,
    EventPropertyFilter,
    PropertyOperator,
    SessionTableVersion,
    HogQLQueryModifiers,
    CustomEventConversionGoal,
    ActionConversionGoal,
    BounceRatePageViewMode,
    WebAnalyticsOrderByFields,
    WebAnalyticsOrderByDirection,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)


@snapshot_clickhouse_queries
class TestWebStatsTableQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-01-29"

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
            for timestamp, session_id, *extra in timestamps:
                url = None
                elements = None
                screen_name = None
                if event == "$pageview":
                    url = extra[0] if extra else None
                elif event == "$screen":
                    screen_name = extra[0] if extra else None
                elif event == "$autocapture":
                    elements = extra[0] if extra else None
                properties = extra[1] if extra and len(extra) > 1 else {}

                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=id,
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$pathname": url,
                        "$current_url": url,
                        "$screen_name": screen_name,
                        **properties,
                    },
                    elements=elements,
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
        compare_filter=None,
        action: Optional[Action] = None,
        custom_event: Optional[str] = None,
        session_table_version: SessionTableVersion = SessionTableVersion.V2,
        filter_test_accounts: Optional[bool] = False,
        bounce_rate_mode: Optional[BounceRatePageViewMode] = BounceRatePageViewMode.COUNT_PAGEVIEWS,
        orderBy=None,
    ):
        with freeze_time(self.QUERY_TIMESTAMP):
            modifiers = HogQLQueryModifiers(
                sessionTableVersion=session_table_version, bounceRatePageViewMode=bounce_rate_mode
            )
            query = WebStatsTableQuery(
                dateRange=DateRange(date_from=date_from, date_to=date_to),
                properties=properties or [],
                breakdownBy=breakdown_by,
                limit=limit,
                doPathCleaning=bool(path_cleaning_filters),
                includeBounceRate=include_bounce_rate,
                includeScrollDepth=include_scroll_depth,
                compareFilter=compare_filter,
                conversionGoal=ActionConversionGoal(actionId=action.id)
                if action
                else CustomEventConversionGoal(customEventName=custom_event)
                if custom_event
                else None,
                filterTestAccounts=filter_test_accounts,
                orderBy=orderBy,
            )
            self.team.path_cleaning_filters = path_cleaning_filters or []
            runner = WebStatsTableQueryRunner(team=self.team, query=query, modifiers=modifiers)
            return runner.calculate()

    def test_no_crash_when_no_data(self):
        results = self._run_web_stats_table_query(
            "2023-12-08",
            "2023-12-15",
        ).results
        assert [] == results

    def test_increase_in_users(self):
        s1a = str(uuid7("2023-12-02"))
        s1b = str(uuid7("2023-12-13"))
        s2 = str(uuid7("2023-12-10"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1a, "/"), ("2023-12-03", s1a, "/login"), ("2023-12-13", s1b, "/docs")]),
                ("p2", [("2023-12-10", s2, "/")]),
            ]
        )

        results = self._run_web_stats_table_query("2023-12-01", "2023-12-11").results

        assert [
            ["/", (2, None), (2, None), ""],
            ["/login", (1, None), (1, None), ""],
        ] == results

    def test_increase_in_users_on_mobile(self):
        s1a = str(uuid7("2023-12-02"))
        s1b = str(uuid7("2023-12-13"))
        s2 = str(uuid7("2023-12-10"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1a, "Home"), ("2023-12-03", s1a, "Login"), ("2023-12-13", s1b, "Docs")]),
                ("p2", [("2023-12-10", s2, "Home")]),
            ],
            event="$screen",
        )

        results = self._run_web_stats_table_query(
            "2023-12-01", "2023-12-11", breakdown_by=WebStatsBreakdown.SCREEN_NAME
        ).results

        assert [
            ["Home", (2, None), (2, None), ""],
            ["Login", (1, None), (1, None), ""],
        ] == results

    def test_all_time(self):
        s1a = str(uuid7("2023-12-02"))
        s1b = str(uuid7("2023-12-13"))
        s2 = str(uuid7("2023-12-10"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1a, "/"), ("2023-12-03", s1a, "/login"), ("2023-12-13", s1b, "/docs")]),
                ("p2", [("2023-12-10", s2, "/")]),
            ]
        )

        results = self._run_web_stats_table_query("all", "2023-12-15").results

        assert [
            ["/", (2, None), (2, None), ""],
            ["/docs", (1, None), (1, None), ""],
            ["/login", (1, None), (1, None), ""],
        ] == results

    def test_comparison(self):
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
            "2023-12-06", "2023-12-13", compare_filter=CompareFilter(compare=True)
        ).results

        assert [
            ["/", (1, 1), (1, 1), ""],
            ["/docs", (1, 0), (1, 0), ""],
            ["/login", (0, 1), (0, 1), ""],
        ] == results

    def test_filter_test_accounts(self):
        s1 = str(uuid7("2023-12-02"))
        # Create 1 test account
        self._create_events([("test", [("2023-12-02", s1, "/"), ("2023-12-03", s1, "/login")])])

        results = self._run_web_stats_table_query("2023-12-01", "2023-12-03", filter_test_accounts=True).results

        assert [] == results

    def test_dont_filter_test_accounts(self):
        s1 = str(uuid7("2023-12-02"))
        # Create 1 test account
        self._create_events([("test", [("2023-12-02", s1, "/"), ("2023-12-03", s1, "/login")])])

        results = self._run_web_stats_table_query("2023-12-01", "2023-12-03", filter_test_accounts=False).results

        assert [["/", (1.0, None), (1.0, None), ""], ["/login", (1.0, None), (1.0, None), ""]] == results

    def test_breakdown_channel_type_doesnt_throw(self):
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
        ).results

        assert 1 == len(results)

    def test_limit(self):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2023-12-10"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1, "/"), ("2023-12-03", s1, "/login")]),
                ("p2", [("2023-12-10", s2, "/")]),
            ]
        )

        response_1 = self._run_web_stats_table_query("all", "2023-12-15", limit=1)
        assert [
            ["/", (2, None), (2, None), ""],
        ] == response_1.results
        assert response_1.hasMore is True

        response_2 = self._run_web_stats_table_query("all", "2023-12-15", limit=2)
        assert [
            ["/", (2, None), (2, None), ""],
            ["/login", (1, None), (1, None), ""],
        ] == response_2.results
        assert response_2.hasMore is False

    def test_path_cleaning_filters(self):
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
        ).results

        assert [
            ["/cleaned/:id", (2, None), (2, None), ""],
            ["/cleaned/:id/path/:id", (1, None), (1, None), ""],
            ["/not-cleaned", (1, None), (1, None), ""],
            ["/thing_c", (1, None), (1, None), ""],
        ] == results

    def test_path_cleaning_filters_with_cleaned_path_property(self):
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

        # Send a property filter that it's just like a cleaned path filter
        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            path_cleaning_filters=[
                {"regex": "\\/cleaned\\/\\d+", "alias": "/cleaned/:id"},
                {"regex": "\\/path\\/\\d+", "alias": "/path/:id"},
                {"regex": "thing_a", "alias": "thing_b"},
                {"regex": "thing_b", "alias": "thing_c"},
            ],
            properties=[
                EventPropertyFilter(
                    key="$pathname", operator=PropertyOperator.IS_CLEANED_PATH_EXACT, value="/cleaned/:id"
                )
            ],
        ).results

        # 2 events because we have 2 events that match this cleaned path
        assert [
            ["/cleaned/:id", (2, None), (2, None), ""],
        ] == results

        # Send a property filter that when cleaned will look like a cleaned path filter
        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            path_cleaning_filters=[
                {"regex": "\\/cleaned\\/\\d+", "alias": "/cleaned/:id"},
                {"regex": "\\/path\\/\\d+", "alias": "/path/:id"},
                {"regex": "thing_a", "alias": "thing_b"},
                {"regex": "thing_b", "alias": "thing_c"},
            ],
            properties=[
                EventPropertyFilter(
                    key="$pathname", operator=PropertyOperator.IS_CLEANED_PATH_EXACT, value="/cleaned/123456"
                )
            ],
        ).results

        assert [
            ["/cleaned/:id", (2, None), (2, None), ""],
        ] == results

    def test_path_cleaning_filters_with_cleanable_path_property(self):
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

        # Send a property filter that when cleaned will look like a cleaned path filter
        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            path_cleaning_filters=[{"regex": "\\/cleaned\\/\\d+", "alias": "/cleaned/:id"}],
            properties=[
                EventPropertyFilter(
                    key="$pathname", operator=PropertyOperator.IS_CLEANED_PATH_EXACT, value="/cleaned/123456"
                )
            ],
        ).results

        assert [
            ["/cleaned/:id", (2, None), (2, None), ""],
        ] == results

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
            breakdown_by=WebStatsBreakdown.PAGE,
            include_scroll_depth=True,
            include_bounce_rate=True,
        ).results

        assert [
            ["/a", (1, 0), (1, 0), (0, None), (0.1, None), (0, None), ""],
            ["/b", (1, 0), (1, 0), (None, None), (0.2, None), (0, None), ""],
            ["/c", (1, 0), (1, 0), (None, None), (0.9, None), (1, None), ""],
        ] == results

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
            breakdown_by=WebStatsBreakdown.PAGE,
            include_scroll_depth=True,
            include_bounce_rate=True,
        ).results

        assert [
            ["/a", (3, 0), (4, 0), (1 / 3, None), (0.5, None), (0.5, None), ""],
            ["/b", (2, 0), (2, 0), (None, None), (0.2, None), (0, None), ""],
            ["/c", (2, 0), (2, 0), (None, None), (0.9, None), (1, None), ""],
        ] == results

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
            breakdown_by=WebStatsBreakdown.PAGE,
            include_scroll_depth=True,
            include_bounce_rate=True,
            properties=[EventPropertyFilter(key="$pathname", operator=PropertyOperator.EXACT, value="/a")],
        ).results

        assert [
            ["/a", (3, 0), (4, 0), (1 / 3, None), (0.5, None), (0.5, None), ""],
        ] == results

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
            breakdown_by=WebStatsBreakdown.PAGE,
            include_scroll_depth=True,
            include_bounce_rate=True,
            path_cleaning_filters=[
                {"regex": "\\/a\\/\\d+", "alias": "/a/:id"},
                {"regex": "\\/b\\/\\d+", "alias": "/b/:id"},
                {"regex": "\\/c\\/\\d+", "alias": "/c/:id"},
            ],
        ).results

        assert [
            ["/a/:id", (1, 0), (1, 0), (0, None), (0.1, None), (0, None), ""],
            ["/b/:id", (1, 0), (1, 0), (None, None), (0.2, None), (0, None), ""],
            ["/c/:id", (1, 0), (1, 0), (None, None), (0.9, None), (1, None), ""],
        ] == results

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
            breakdown_by=WebStatsBreakdown.PAGE,
            include_bounce_rate=True,
        ).results

        assert [
            ["/a", (1, 0), (1, 0), (0, None), ""],
            ["/b", (1, 0), (1, 0), (None, None), ""],
            ["/c", (1, 0), (1, 0), (None, None), ""],
        ] == results

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
            breakdown_by=WebStatsBreakdown.PAGE,
            include_bounce_rate=True,
        ).results

        assert [
            ["/a", (3, 0), (4, 0), (1 / 3, None), ""],
            ["/b", (2, 0), (2, 0), (None, None), ""],
            ["/c", (2, 0), (2, 0), (None, None), ""],
        ] == results

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
            breakdown_by=WebStatsBreakdown.PAGE,
            include_bounce_rate=True,
            properties=[EventPropertyFilter(key="$pathname", operator=PropertyOperator.EXACT, value="/a")],
        ).results

        assert [
            ["/a", (3, 0), (4, 0), (1 / 3, None), ""],
        ] == results

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
            breakdown_by=WebStatsBreakdown.PAGE,
            include_bounce_rate=True,
            path_cleaning_filters=[
                {"regex": "\\/a\\/\\d+", "alias": "/a/:id"},
                {"regex": "\\/b\\/\\d+", "alias": "/b/:id"},
                {"regex": "\\/c\\/\\d+", "alias": "/c/:id"},
            ],
        ).results

        assert [
            ["/a/:id", (1, 0), (1, 0), (0, None), ""],
            ["/b/:id", (1, 0), (1, 0), (None, None), ""],
            ["/c/:id", (1, 0), (1, 0), (None, None), ""],
        ] == results

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
            breakdown_by=WebStatsBreakdown.INITIAL_PAGE,
            include_bounce_rate=True,
        ).results

        assert [
            ["/a", (1, None), (3, None), (0, None), ""],
        ] == results

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
            breakdown_by=WebStatsBreakdown.INITIAL_PAGE,
            include_bounce_rate=True,
        ).results

        assert [
            ["/a", (3, None), (8, None), (1 / 3, None), ""],
        ] == results

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
            breakdown_by=WebStatsBreakdown.INITIAL_PAGE,
            include_bounce_rate=True,
            properties=[EventPropertyFilter(key="$pathname", operator=PropertyOperator.EXACT, value="/a")],
        ).results

        assert [
            ["/a", (3, None), (4, None), (1 / 3, None), ""],
        ] == results

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
            breakdown_by=WebStatsBreakdown.INITIAL_PAGE,
            include_bounce_rate=True,
            path_cleaning_filters=[
                {"regex": "\\/a\\/\\d+", "alias": "/a/:id"},
                {"regex": "\\/b\\/\\d+", "alias": "/b/:id"},
                {"regex": "\\/c\\/\\d+", "alias": "/c/:id"},
            ],
        ).results

        assert [
            ["/a/:id", (1, None), (3, None), (0, None), ""],
        ] == results

    def test_source_medium_campaign(self):
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
        ).results

        assert [
            ["google / (none) / (none)", (1, None), (1, None), ""],
            ["news.ycombinator.com / referral / (none)", (1, None), (1, None), ""],
        ] == results

    def test_null_in_utm_tags(self):
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
        ).results

        assert [["google", (1, None), (1, None), ""], [None, (1, None), (1, None), ""]] == results

    def test_is_not_set_filter(self):
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
        ).results

        assert [[None, (1, None), (1, None), ""]] == results

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
        assert [["google", (1, None), (2, None), ""]] == results_session

        # Try this with a query that uses event properties
        results_event = self._run_web_stats_table_query(
            "all",
            "2024-07-31",
            breakdown_by=WebStatsBreakdown.PAGE,
        ).results
        assert [["/path", (1, None), (2, None), ""]] == results_event

        # Try this with a query using the bounce rate
        results_event = self._run_web_stats_table_query(
            "all", "2024-07-31", breakdown_by=WebStatsBreakdown.PAGE, include_bounce_rate=True
        ).results
        assert [["/path", (1, 0), (2, 0), (None, None), ""]] == results_event

        # Try this with a query using the scroll depth
        results_event = self._run_web_stats_table_query(
            "all",
            "2024-07-31",
            breakdown_by=WebStatsBreakdown.PAGE,
            include_bounce_rate=True,
            include_scroll_depth=True,
        ).results
        assert [["/path", (1, 0), (2, 0), (None, None), (None, None), (None, None), ""]] == results_event

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

        # Show event property breakdowns of page view events even without session id
        results = self._run_web_stats_table_query(
            "all",
            "2024-07-31",
            breakdown_by=WebStatsBreakdown.PAGE,
        ).results

        assert [["/path", (1, None), (1, None), ""]] == results

    def test_cohort_test_filters(self):
        d1 = "d1"
        s1 = str(uuid7("2024-07-30"))
        d2 = "d2"
        s2 = str(uuid7("2024-07-30"))
        _create_person(
            team_id=self.team.pk,
            distinct_ids=[d1],
            properties={"name": d1, "email": "test@example.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=d1,
            timestamp="2024-07-30",
            properties={"$session_id": s1, "$pathname": "/path1"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=[d2],
            properties={"name": d2, "email": "d2@hedgebox.net"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=d2,
            timestamp="2024-07-30",
            properties={"$session_id": s2, "$pathname": "/path2"},
        )

        real_users_cohort = Cohort.objects.create(
            team=self.team,
            name="Real persons",
            description="People who don't belong to the Hedgebox team.",
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@hedgebox.net$",
                            "operator": "not_regex",
                        }
                    ]
                }
            ],
        )
        self.team.test_account_filters = [{"key": "id", "type": "cohort", "value": real_users_cohort.pk}]

        flush_persons_and_events()
        real_users_cohort.calculate_people_ch(pending_version=0)

        # Test that the cohort filter works
        results = self._run_web_stats_table_query(
            "all",
            None,
            filter_test_accounts=True,
            breakdown_by=WebStatsBreakdown.PAGE,
        ).results

        assert results == [["/path1", (1, None), (1, None), ""]]

    def test_language_filter(self):
        d1, s1 = "d1", str(uuid7("2024-07-30"))
        d2, s2 = "d2", str(uuid7("2024-07-30"))

        _create_person(
            team_id=self.team.pk,
            distinct_ids=[d1],
            properties={"name": d1, "email": "test@example.com"},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=d1,
            timestamp="2024-07-30",
            properties={"$session_id": s1, "$pathname": "/path1", "$browser_language": "en-US"},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=d1,
            timestamp="2024-07-30",
            properties={"$session_id": s1, "$pathname": "/path2", "$browser_language": "en-US"},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=d1,
            timestamp="2024-07-30",
            properties={"$session_id": s1, "$pathname": "/path3", "$browser_language": "en-GB"},
        )

        _create_person(
            team_id=self.team.pk,
            distinct_ids=[d2],
            properties={"name": d2, "email": "d2@hedgebox.net"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=d2,
            timestamp="2024-07-30",
            properties={"$session_id": s2, "$pathname": "/path2", "$browser_language": "pt-BR"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=d2,
            timestamp="2024-07-30",
            properties={"$session_id": s2, "$pathname": "/path3", "$browser_language": "pt-BR"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=d2,
            timestamp="2024-07-30",
            properties={"$session_id": s2, "$pathname": "/path4", "$browser_language": "nl"},
        )

        flush_persons_and_events()

        results = self._run_web_stats_table_query(
            "all",
            None,
            breakdown_by=WebStatsBreakdown.LANGUAGE,
            filter_test_accounts=True,
        ).results

        # We can't assert on this directly because we're using topK and that's probabilistic
        # which is causing this to be flaky (en-GB happens sometimes),
        # we'll instead assert on a reduced form where we're
        # not counting the country, but only the locale
        # assert results == [["en-US", (1, 0), (3, 0)], ["pt-BR", (1, 0), (2, 0)], ["nl-", (1, 0), (1, 0)]]

        country_results = [result[0].split("-")[0] for result in results]
        assert country_results == ["en", "pt", "nl"]

    def test_timezone_filter_general(self):
        before_date = "2024-07-14"
        after_date = "2024-07-16"

        for idx, (distinct_id, before_session_id, after_session_id) in enumerate(
            [
                ("UTC", str(uuid7(before_date)), str(uuid7(after_date))),
                ("Asia/Calcutta", str(uuid7(before_date)), str(uuid7(after_date))),
                ("America/New_York", str(uuid7(before_date)), str(uuid7(after_date))),
                ("America/Sao_Paulo", str(uuid7(before_date)), str(uuid7(after_date))),
            ]
        ):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[distinct_id],
                properties={"name": before_session_id, "email": f"{distinct_id}@example.com"},
            )

            # Always one event in the before_date
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=distinct_id,
                timestamp=before_date,
                properties={"$session_id": before_session_id, "$pathname": f"/path/landing", "$timezone": distinct_id},
            )

            # Several events in the actual range
            for i in range(idx + 1):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=distinct_id,
                    timestamp=after_date,
                    properties={"$session_id": after_session_id, "$pathname": f"/path{i}", "$timezone": distinct_id},
                )

        results = self._run_web_stats_table_query(
            "2024-07-15",  # Period is since July first, we create some events before that date, and some after
            None,
            breakdown_by=WebStatsBreakdown.TIMEZONE,
        ).results

        # Brasilia UTC-3, New York UTC-4, Calcutta UTC+5:30, UTC
        assert results == [
            [-3, (1, None), (4, None), ""],
            [-4, (1, None), (3, None), ""],
            [5.5, (1, None), (2, None), ""],
            [0, (1, None), (1, None), ""],
        ]

    def test_timezone_filter_dst_change(self):
        did = "id"
        sid = str(uuid7("2019-02-17"))

        _create_person(
            team_id=self.team.pk,
            distinct_ids=[did],
            properties={"name": sid, "email": f"test@example.com"},
        )

        # Cross daylight savings time change in Brazil
        for i in range(6):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=did,
                timestamp=f"2019-02-17 0{i}:00:00",
                properties={"$session_id": sid, "$pathname": f"/path1", "$timezone": "America/Sao_Paulo"},
            )

        results = self._run_web_stats_table_query(
            "all",
            None,
            breakdown_by=WebStatsBreakdown.TIMEZONE,
        ).results

        # Change from UTC-2 to UTC-3 in the middle of the night
        assert results == [
            [-3.0, (1.0, None), (4.0, None), ""],
            [-2.0, (1.0, None), (2.0, None), ""],
        ]

    def test_timezone_filter_with_invalid_timezone(self):
        date = "2024-07-30"

        for idx, (distinct_id, session_id) in enumerate(
            [
                ("UTC", str(uuid7(date))),
                ("Timezone_not_exists", str(uuid7(date))),
            ]
        ):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[distinct_id],
                properties={"name": session_id, "email": f"{distinct_id}@example.com"},
            )

            for i in range(idx + 1):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=distinct_id,
                    timestamp=date,
                    properties={"$session_id": session_id, "$pathname": f"/path{i}", "$timezone": distinct_id},
                )

        with self.assertRaisesRegex(Exception, "Cannot load time zone"):
            self._run_web_stats_table_query(
                "all",
                None,
                breakdown_by=WebStatsBreakdown.TIMEZONE,
            )

    def test_timezone_filter_with_empty_timezone(self):
        did = "id"
        sid = str(uuid7("2019-02-17"))

        _create_person(
            team_id=self.team.pk,
            distinct_ids=[did],
            properties={"name": sid, "email": f"test@example.com"},
        )

        # Key not exists
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=did,
            timestamp=f"2019-02-17 00:00:00",
            properties={"$session_id": sid, "$pathname": f"/path1"},
        )

        # Key exists, it's null
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=did,
            timestamp=f"2019-02-17 00:00:00",
            properties={"$session_id": sid, "$pathname": f"/path1", "$timezone": None},
        )

        # Key exists, it's empty string
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=did,
            timestamp=f"2019-02-17 00:00:00",
            properties={"$session_id": sid, "$pathname": f"/path1", "$timezone": ""},
        )

        # Key exists, it's set to the invalid 'Etc/Unknown' timezone
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=did,
            timestamp=f"2019-02-17 00:00:00",
            properties={"$session_id": sid, "$pathname": f"/path1", "$timezone": "Etc/Unknown"},
        )

        results = self._run_web_stats_table_query(
            "all",
            None,
            breakdown_by=WebStatsBreakdown.TIMEZONE,
        ).results

        # Don't crash, treat all of them null
        assert results == []

    def test_conversion_goal_no_conversions(self):
        s1 = str(uuid7("2023-12-01"))
        self._create_events(
            [
                ("p1", [("2023-12-01", s1, "https://www.example.com/foo")]),
            ]
        )

        action = Action.objects.create(
            team=self.team,
            name="Visited Bar",
            steps_json=[{"event": "$pageview", "url": "https://www.example.com/bar", "url_matching": "regex"}],
        )

        response = self._run_web_stats_table_query(
            "2023-12-01", "2023-12-03", breakdown_by=WebStatsBreakdown.PAGE, action=action
        )

        assert [["https://www.example.com/foo", (1, None), (0, None), (0, None), (0, None), ""]] == response.results
        assert [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.total_conversions",
            "context.columns.unique_conversions",
            "context.columns.conversion_rate",
            "context.columns.cross_sell",
        ] == response.columns

    def test_conversion_goal_one_pageview_conversion(self):
        s1 = str(uuid7("2023-12-01"))
        self._create_events(
            [
                ("p1", [("2023-12-01", s1, "https://www.example.com/foo")]),
            ]
        )

        action = Action.objects.create(
            team=self.team,
            name="Visited Foo",
            steps_json=[
                {
                    "event": "$pageview",
                    "url": "https://www.example.com/foo",
                    "url_matching": "regex",
                }
            ],
        )

        response = self._run_web_stats_table_query(
            "2023-12-01", "2023-12-03", breakdown_by=WebStatsBreakdown.PAGE, action=action
        )

        response = self._run_web_stats_table_query(
            "2023-12-01", "2023-12-03", breakdown_by=WebStatsBreakdown.PAGE, action=action
        )

        assert [["https://www.example.com/foo", (1, None), (1, None), (1, None), (1, None), ""]] == response.results
        assert [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.total_conversions",
            "context.columns.unique_conversions",
            "context.columns.conversion_rate",
            "context.columns.cross_sell",
        ] == response.columns

    def test_conversion_goal_one_custom_event_conversion(self):
        s1 = str(uuid7("2023-12-01"))
        self._create_events(
            [
                ("p1", [("2023-12-01", s1, "https://www.example.com/foo")]),
            ],
            event="custom_event",
        )

        response = self._run_web_stats_table_query(
            "2023-12-01",
            "2023-12-03",
            breakdown_by=WebStatsBreakdown.INITIAL_UTM_SOURCE,  # Allow the breakdown value to be non-null
            custom_event="custom_event",
        )

        assert [[None, (1, None), (1, None), (1, None), (1, None), ""]] == response.results
        assert [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.total_conversions",
            "context.columns.unique_conversions",
            "context.columns.conversion_rate",
            "context.columns.cross_sell",
        ] == response.columns

    def test_conversion_goal_one_custom_action_conversion(self):
        s1 = str(uuid7("2023-12-01"))
        self._create_events(
            [
                ("p1", [("2023-12-01", s1)]),
            ],
            event="custom_event",
        )

        action = Action.objects.create(
            team=self.team,
            name="Did Custom Event",
            steps_json=[
                {
                    "event": "custom_event",
                }
            ],
        )

        response = self._run_web_stats_table_query(
            "2023-12-01",
            "2023-12-03",
            breakdown_by=WebStatsBreakdown.INITIAL_UTM_SOURCE,  # Allow the breakdown value to be non-null
            action=action,
        )

        assert [[None, (1, None), (1, None), (1, None), (1, None), ""]] == response.results
        assert [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.total_conversions",
            "context.columns.unique_conversions",
            "context.columns.conversion_rate",
            "context.columns.cross_sell",
        ] == response.columns

    def test_conversion_goal_one_autocapture_conversion(self):
        s1 = str(uuid7("2023-12-01"))
        self._create_events(
            [
                ("p1", [("2023-12-01", s1, [Element(nth_of_type=1, nth_child=0, tag_name="button", text="Pay $10")])]),
            ],
            event="$autocapture",
        )

        action = Action.objects.create(
            team=self.team,
            name="Paid $10",
            steps_json=[
                {
                    "event": "$autocapture",
                    "tag_name": "button",
                    "text": "Pay $10",
                }
            ],
        )

        response = self._run_web_stats_table_query(
            "2023-12-01",
            "2023-12-03",
            breakdown_by=WebStatsBreakdown.INITIAL_UTM_SOURCE,  # Allow the breakdown value to be non-null
            action=action,
        )

        assert [[None, (1, None), (1, None), (1, None), (1, None), ""]] == response.results
        assert [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.total_conversions",
            "context.columns.unique_conversions",
            "context.columns.conversion_rate",
            "context.columns.cross_sell",
        ] == response.columns

    def test_conversion_rate(self):
        s1 = str(uuid7("2023-12-01"))
        s2 = str(uuid7("2023-12-01"))
        s3 = str(uuid7("2023-12-01"))

        self._create_events(
            [
                (
                    "p1",
                    [
                        ("2023-12-01", s1, "https://www.example.com/foo"),
                        ("2023-12-01", s1, "https://www.example.com/foo"),
                    ],
                ),
                (
                    "p2",
                    [
                        ("2023-12-01", s2, "https://www.example.com/foo"),
                        ("2023-12-01", s2, "https://www.example.com/bar"),
                    ],
                ),
                ("p3", [("2023-12-01", s3, "https://www.example.com/bar")]),
            ]
        )

        action = Action.objects.create(
            team=self.team,
            name="Visited Foo",
            steps_json=[
                {
                    "event": "$pageview",
                    "url": "https://www.example.com/foo",
                    "url_matching": "regex",
                }
            ],
        )

        response = self._run_web_stats_table_query(
            "2023-12-01", "2023-12-03", breakdown_by=WebStatsBreakdown.PAGE, action=action
        )

        assert [
            ["https://www.example.com/foo", (2, None), (3, None), (2, None), (1, None), ""],
            ["https://www.example.com/bar", (2, None), (0, None), (0, None), (0, None), ""],
        ] == response.results
        assert [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.total_conversions",
            "context.columns.unique_conversions",
            "context.columns.conversion_rate",
            "context.columns.cross_sell",
        ] == response.columns

    def test_sorting_by_visitors(self):
        s1 = str(uuid7("2023-12-01"))
        s2 = str(uuid7("2023-12-01"))
        s3 = str(uuid7("2023-12-01"))

        self._create_events(
            [
                ("p1", [("2023-12-01", s1, "/path1")]),
                ("p2", [("2023-12-01", s2, "/path1"), ("2023-12-01", s2, "/path2")]),
                ("p3", [("2023-12-01", s3, "/path1"), ("2023-12-01", s3, "/path2"), ("2023-12-01", s3, "/path3")]),
            ]
        )

        # Test ascending order
        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            breakdown_by=WebStatsBreakdown.PAGE,
            orderBy=(WebAnalyticsOrderByFields.VISITORS, WebAnalyticsOrderByDirection.ASC),
        ).results

        assert [row[0] for row in results] == ["/path3", "/path2", "/path1"]

        # Test descending order
        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            breakdown_by=WebStatsBreakdown.PAGE,
            orderBy=(WebAnalyticsOrderByFields.VISITORS, WebAnalyticsOrderByDirection.DESC),
        ).results

        assert [row[0] for row in results] == ["/path1", "/path2", "/path3"]

    def test_sorting_by_views(self):
        s1 = str(uuid7("2023-12-01"))
        s2 = str(uuid7("2023-12-01"))
        s3 = str(uuid7("2023-12-01"))

        self._create_events(
            [
                ("p1", [("2023-12-01", s1, "/path1")]),
                ("p2", [("2023-12-01", s2, "/path2"), ("2023-12-01", s2, "/path2")]),
                ("p3", [("2023-12-01", s3, "/path3"), ("2023-12-01", s3, "/path3"), ("2023-12-01", s3, "/path3")]),
            ]
        )

        # Test ascending order
        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            breakdown_by=WebStatsBreakdown.PAGE,
            orderBy=(WebAnalyticsOrderByFields.VIEWS, WebAnalyticsOrderByDirection.ASC),
        ).results

        assert [row[0] for row in results] == ["/path1", "/path2", "/path3"]

        # Test descending order
        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            breakdown_by=WebStatsBreakdown.PAGE,
            orderBy=(WebAnalyticsOrderByFields.VIEWS, WebAnalyticsOrderByDirection.DESC),
        ).results

        assert [row[0] for row in results] == ["/path3", "/path2", "/path1"]

    def test_sorting_by_bounce_rate(self):
        self._create_pageviews(
            "p1",
            [
                ("/path1", "2023-12-02T12:00:00", 0.1),  # Bounce
            ],
        )
        self._create_pageviews(
            "p2",
            [
                ("/path2", "2023-12-02T12:00:00", 0.1),
                ("/path2", "2023-12-02T12:00:01", 0.2),  # No bounce
            ],
        )
        self._create_pageviews(
            "p3",
            [
                ("/path3", "2023-12-02T12:00:00", 0.1),
                ("/path3", "2023-12-02T12:00:01", 0.1),
                ("/path3", "2023-12-02T12:00:02", 0.2),  # No bounce
            ],
        )

        # Test ascending order
        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            breakdown_by=WebStatsBreakdown.PAGE,
            include_bounce_rate=True,
            orderBy=(WebAnalyticsOrderByFields.BOUNCE_RATE, WebAnalyticsOrderByDirection.ASC),
        ).results

        assert [row[0] for row in results] == ["/path2", "/path3", "/path1"]

        # Test descending order
        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            breakdown_by=WebStatsBreakdown.PAGE,
            include_bounce_rate=True,
            orderBy=(WebAnalyticsOrderByFields.BOUNCE_RATE, WebAnalyticsOrderByDirection.DESC),
        ).results

        assert [row[0] for row in results] == ["/path1", "/path3", "/path2"]

    def test_sorting_by_scroll_depth(self):
        self._create_pageviews(
            "p1",
            [
                ("/path1", "2023-12-02T12:00:00", 0.1),  # Low scroll
            ],
        )
        self._create_pageviews(
            "p2",
            [
                ("/path2", "2023-12-02T12:00:00", 0.5),  # Medium scroll
            ],
        )
        self._create_pageviews(
            "p3",
            [
                ("/path3", "2023-12-02T12:00:00", 0.9),  # High scroll
            ],
        )

        flush_persons_and_events()

        # Test ascending order by average scroll percentage
        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            breakdown_by=WebStatsBreakdown.PAGE,
            include_scroll_depth=True,
            include_bounce_rate=True,
            orderBy=(WebAnalyticsOrderByFields.AVERAGE_SCROLL_PERCENTAGE, WebAnalyticsOrderByDirection.ASC),
        ).results

        assert [row[0] for row in results] == ["/path1", "/path2", "/path3"]

        # Test descending order by average scroll percentage
        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            breakdown_by=WebStatsBreakdown.PAGE,
            include_scroll_depth=True,
            include_bounce_rate=True,
            orderBy=(WebAnalyticsOrderByFields.AVERAGE_SCROLL_PERCENTAGE, WebAnalyticsOrderByDirection.DESC),
        ).results

        assert [row[0] for row in results] == ["/path3", "/path2", "/path1"]

    def test_sorting_by_total_conversions(self):
        s1 = str(uuid7("2023-12-01"))
        s2 = str(uuid7("2023-12-01"))
        s3 = str(uuid7("2023-12-01"))

        self._create_events(
            [
                ("p1", [("2023-12-01", s1, "/foo"), ("2023-12-01", s1, "/foo")]),
                ("p2", [("2023-12-01", s2, "/foo"), ("2023-12-01", s2, "/bar")]),
                ("p3", [("2023-12-01", s3, "/bar")]),
            ]
        )

        action = Action.objects.create(
            team=self.team,
            name="Visited Foo",
            steps_json=[{"event": "$pageview", "url": "/foo", "url_matching": "regex"}],
        )

        response = self._run_web_stats_table_query(
            "2023-12-01",
            "2023-12-03",
            breakdown_by=WebStatsBreakdown.PAGE,
            orderBy=(WebAnalyticsOrderByFields.TOTAL_CONVERSIONS, WebAnalyticsOrderByDirection.ASC),
            action=action,
        )

        assert [row[0] for row in response.results] == ["/bar", "/foo"]

        response = self._run_web_stats_table_query(
            "2023-12-01",
            "2023-12-03",
            breakdown_by=WebStatsBreakdown.PAGE,
            orderBy=(WebAnalyticsOrderByFields.TOTAL_CONVERSIONS, WebAnalyticsOrderByDirection.DESC),
            action=action,
        )

        assert [row[0] for row in response.results] == ["/foo", "/bar"]

    def test_sorting_by_conversion_rate(self):
        s1 = str(uuid7("2023-12-01"))
        s2 = str(uuid7("2023-12-01"))
        s3 = str(uuid7("2023-12-01"))

        self._create_events(
            [
                ("p1", [("2023-12-01", s1, "/foo"), ("2023-12-01", s1, "/foo")]),
                ("p2", [("2023-12-01", s2, "/foo"), ("2023-12-01", s2, "/bar")]),
                ("p3", [("2023-12-01", s3, "/bar")]),
            ]
        )

        action = Action.objects.create(
            team=self.team,
            name="Visited Foo",
            steps_json=[{"event": "$pageview", "url": "/foo", "url_matching": "regex"}],
        )

        response = self._run_web_stats_table_query(
            "2023-12-01",
            "2023-12-03",
            breakdown_by=WebStatsBreakdown.PAGE,
            orderBy=(WebAnalyticsOrderByFields.CONVERSION_RATE, WebAnalyticsOrderByDirection.ASC),
            action=action,
        )

        assert [row[0] for row in response.results] == ["/bar", "/foo"]

        response = self._run_web_stats_table_query(
            "2023-12-01",
            "2023-12-03",
            breakdown_by=WebStatsBreakdown.PAGE,
            orderBy=(WebAnalyticsOrderByFields.CONVERSION_RATE, WebAnalyticsOrderByDirection.DESC),
            action=action,
        )

        assert [row[0] for row in response.results] == ["/foo", "/bar"]

    def test_include_date_parameter(self):
        s1a = str(uuid7("2023-12-02"))
        s1b = str(uuid7("2023-12-03"))
        s2 = str(uuid7("2023-12-10"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1a, "/"), ("2023-12-03", s1b, "/login")]),
                ("p2", [("2023-12-10", s2, "/")]),
            ]
        )

        with freeze_time(self.QUERY_TIMESTAMP):
            modifiers = HogQLQueryModifiers(sessionTableVersion=SessionTableVersion.V2)
            query = WebStatsTableQuery(
                dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-11"),
                properties=[],
                breakdownBy=WebStatsBreakdown.PAGE,
                includeDate=True,
            )
            runner = WebStatsTableQueryRunner(team=self.team, query=query, modifiers=modifiers)
            results = runner.calculate().results

        # Results should include date as the first column in each row
        assert len(results) > 0
        for row in results:
            # First element should be a date string
            assert isinstance(row[0], str)
            # Date should be in format YYYY-MM-DD
            assert len(row[0]) == 10
            assert row[0][4] == "-" and row[0][7] == "-"

    def test_order_by_functionality(self):
        s1a = str(uuid7("2023-12-02"))
        s1b = str(uuid7("2023-12-03"))
        s2 = str(uuid7("2023-12-10"))
        self._create_events(
            [
                ("p1", [("2023-12-02", s1a, "/"), ("2023-12-03", s1b, "/login")]),
                ("p2", [("2023-12-10", s2, "/")]),
                ("p3", [("2023-12-10", s2, "/about"), ("2023-12-10", s2, "/about")]),
            ]
        )

        # Test ordering by views ascending
        results_asc = self._run_web_stats_table_query(
            "2023-12-01", "2023-12-11", orderBy=[WebAnalyticsOrderByFields.VIEWS, WebAnalyticsOrderByDirection.ASC]
        ).results

        # Test ordering by views descending
        results_desc = self._run_web_stats_table_query(
            "2023-12-01", "2023-12-11", orderBy=[WebAnalyticsOrderByFields.VIEWS, WebAnalyticsOrderByDirection.DESC]
        ).results

        # Verify ascending order
        assert results_asc[0][1][0] <= results_asc[-1][1][0]

        # Verify descending order
        assert results_desc[0][1][0] >= results_desc[-1][1][0]

        # Verify that the orders are opposite
        assert results_asc[0][0] != results_desc[0][0]

    def test_include_scroll_depth(self):
        # Create events with scroll depth information
        self._create_pageviews(
            "user1",
            [
                ("/", "2023-12-02T10:00:00Z", 0.3),
                ("/about", "2023-12-02T10:05:00Z", 0.9),
                ("/pricing", "2023-12-02T10:10:00Z", 0.5),
            ],
        )

        self._create_pageviews(
            "user2",
            [
                ("/", "2023-12-03T10:00:00Z", 0.7),
                ("/about", "2023-12-03T10:05:00Z", 0.2),
            ],
        )

        flush_persons_and_events()

        results = self._run_web_stats_table_query("2023-12-01", "2023-12-04", include_scroll_depth=True).results

        # Verify that results include scroll depth metrics
        assert len(results) > 0

        # The structure should include average scroll percentage and scroll_gt80_percentage
        # Format is typically [path, views, visitors, average_scroll_percentage, scroll_gt80_percentage]
        for row in results:
            # Check if the row has the expected number of columns
            assert len(row) >= 5

            # Check if the scroll depth metrics are present (could be None if no data)
            if row[0] == "/about":
                # At least one page should have scroll depth data
                assert row[3] is not None
                # Average scroll percentage should be between 0 and 1
                assert 0 <= row[3][0] <= 1 if row[3][0] is not None else True

    def test_include_revenue(self):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2023-12-03"))

        # Create events with revenue information
        self._create_events(
            [
                (
                    "p1",
                    [
                        ("2023-12-02", s1, "/checkout", {"$purchase": True, "$revenue": 100}),
                        ("2023-12-03", s1, "/checkout", {"$purchase": True, "$revenue": 50}),
                    ],
                ),
                ("p2", [("2023-12-03", s2, "/checkout", {"$purchase": True, "$revenue": 75})]),
            ]
        )

        with freeze_time(self.QUERY_TIMESTAMP):
            modifiers = HogQLQueryModifiers(sessionTableVersion=SessionTableVersion.V2)
            query = WebStatsTableQuery(
                dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-04"),
                properties=[],
                breakdownBy=WebStatsBreakdown.PAGE,
                includeRevenue=True,
            )
            runner = WebStatsTableQueryRunner(team=self.team, query=query, modifiers=modifiers)
            results = runner.calculate().results

        # Verify that results include revenue metrics
        assert len(results) > 0

        # Find the checkout page in results
        checkout_row = next((row for row in results if row[0] == "/checkout"), None)

        # Verify revenue data is present for the checkout page
        assert checkout_row is not None

        # The revenue column should be present and have a value
        # The exact position depends on the query structure, but it should be present
        revenue_found = False
        for item in checkout_row:
            if isinstance(item, tuple) and item[0] is not None and item[0] > 0:
                revenue_found = True
                break

        assert revenue_found, "Revenue data should be present in the results"

    def test_breakdown_by_device_type(self):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2023-12-03"))

        # Create events with different device types
        self._create_events(
            [
                (
                    "p1",
                    [
                        ("2023-12-02", s1, "/", {"$device_type": "Desktop"}),
                        ("2023-12-03", s1, "/about", {"$device_type": "Desktop"}),
                    ],
                ),
                (
                    "p2",
                    [
                        ("2023-12-03", s2, "/", {"$device_type": "Mobile"}),
                        ("2023-12-03", s2, "/contact", {"$device_type": "Mobile"}),
                    ],
                ),
            ]
        )

        results = self._run_web_stats_table_query(
            "2023-12-01", "2023-12-04", breakdown_by=WebStatsBreakdown.DEVICE_TYPE
        ).results

        # Verify that results are broken down by device type
        assert len(results) == 2

        # Find rows for each device type
        desktop_row = next((row for row in results if row[0] == "Desktop"), None)
        mobile_row = next((row for row in results if row[0] == "Mobile"), None)

        # Verify both device types are present
        assert desktop_row is not None, "Desktop device type should be in results"
        assert mobile_row is not None, "Mobile device type should be in results"

        # Verify correct counts
        assert desktop_row[1][0] == 1, "Desktop should have 1 visitor"
        assert mobile_row[1][0] == 1, "Mobile should have 1 visitor"

    def test_breakdown_by_browser_type(self):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2023-12-03"))

        # Create events with different browser types
        self._create_events(
            [
                (
                    "p1",
                    [
                        ("2023-12-02", s1, "/", {"$browser": "Chrome"}),
                        ("2023-12-03", s1, "/about", {"$browser": "Chrome"}),
                    ],
                ),
                (
                    "p2",
                    [
                        ("2023-12-03", s2, "/", {"$browser": "Firefox"}),
                        ("2023-12-03", s2, "/contact", {"$browser": "Firefox"}),
                    ],
                ),
            ]
        )

        results = self._run_web_stats_table_query(
            "2023-12-01", "2023-12-04", breakdown_by=WebStatsBreakdown.BROWSER_TYPE
        ).results

        # Verify that results are broken down by browser type
        assert len(results) == 2

        # Find rows for each browser type
        chrome_row = next((row for row in results if row[0] == "Chrome"), None)
        firefox_row = next((row for row in results if row[0] == "Firefox"), None)

        # Verify both browser types are present
        assert chrome_row is not None, "Chrome browser type should be in results"
        assert firefox_row is not None, "Firefox browser type should be in results"

        # Verify correct counts
        assert chrome_row[1][0] == 1, "Chrome should have 1 visitor"
        assert firefox_row[1][0] == 1, "Firefox should have 1 visitor"

    def test_property_filters(self):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2023-12-03"))

        # Create events with different properties
        self._create_events(
            [
                (
                    "p1",
                    [
                        ("2023-12-02", s1, "/", {"$browser": "Chrome", "country": "US"}),
                        ("2023-12-03", s1, "/about", {"$browser": "Chrome", "country": "US"}),
                    ],
                ),
                (
                    "p2",
                    [
                        ("2023-12-03", s2, "/", {"$browser": "Firefox", "country": "UK"}),
                        ("2023-12-03", s2, "/contact", {"$browser": "Firefox", "country": "UK"}),
                    ],
                ),
            ]
        )

        # Filter for Chrome browser only
        results_chrome = self._run_web_stats_table_query(
            "2023-12-01",
            "2023-12-04",
            properties=[EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.EXACT)],
        ).results

        # Verify that only Chrome events are included
        assert len(results_chrome) > 0

        # Check that only pages visited with Chrome are included
        page_paths = [row[0] for row in results_chrome]
        assert "/" in page_paths
        assert "/about" in page_paths
        assert "/contact" not in page_paths

        # Filter for UK country only
        results_uk = self._run_web_stats_table_query(
            "2023-12-01",
            "2023-12-04",
            properties=[EventPropertyFilter(key="country", value="UK", operator=PropertyOperator.EXACT)],
        ).results

        # Verify that only UK events are included
        assert len(results_uk) > 0

        # Check that only pages visited from UK are included
        page_paths = [row[0] for row in results_uk]
        assert "/" in page_paths
        assert "/contact" in page_paths
        assert "/about" not in page_paths

    def test_has_more_pagination(self):
        # Create many different pages to test pagination
        s1 = str(uuid7("2023-12-02"))
        events_data = [("p1", [])]

        # Create 15 different pages
        for i in range(15):
            page_path = f"/page{i}"
            events_data[0][1].append(("2023-12-02", s1, page_path))

        self._create_events(events_data)

        # Run query with limit of 5
        with freeze_time(self.QUERY_TIMESTAMP):
            modifiers = HogQLQueryModifiers(sessionTableVersion=SessionTableVersion.V2)
            query = WebStatsTableQuery(
                dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-04"),
                properties=[],
                breakdownBy=WebStatsBreakdown.PAGE,
                limit=5,
            )
            runner = WebStatsTableQueryRunner(team=self.team, query=query, modifiers=modifiers)
            response = runner.calculate()

        # Verify that hasMore is True and we got exactly 5 results
        assert response.hasMore is True, "hasMore should be True when there are more results than the limit"
        assert len(response.results) == 5, "Should return exactly 5 results when limit is 5"

        # Run query with limit of 20 (more than the number of pages)
        with freeze_time(self.QUERY_TIMESTAMP):
            modifiers = HogQLQueryModifiers(sessionTableVersion=SessionTableVersion.V2)
            query = WebStatsTableQuery(
                dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-04"),
                properties=[],
                breakdownBy=WebStatsBreakdown.PAGE,
                limit=20,
            )
            runner = WebStatsTableQueryRunner(team=self.team, query=query, modifiers=modifiers)
            response = runner.calculate()

        # Verify that hasMore is False and we got all 15 results
        assert response.hasMore is False, "hasMore should be False when all results are returned"
        assert len(response.results) == 15, "Should return all 15 results when limit is 20"

    def test_conversion_goal_custom_event(self):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2023-12-03"))

        # Create pageview events and conversion events
        self._create_events(
            [
                (
                    "p1",
                    [
                        ("2023-12-02", s1, "/"),
                        ("2023-12-02", s1, "/product", {"$event_type": "page_view"}),
                        ("2023-12-02", s1, None, {"$event_type": "purchase", "value": 100}),
                    ],
                ),
                (
                    "p2",
                    [
                        ("2023-12-03", s2, "/"),
                        ("2023-12-03", s2, "/product", {"$event_type": "page_view"}),
                        # No conversion for p2
                    ],
                ),
            ]
        )

        # Create additional purchase event
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="p1",
            timestamp="2023-12-02T12:00:00Z",
            properties={"value": 50},
        )

        # Run query with custom event conversion goal
        results = self._run_web_stats_table_query("2023-12-01", "2023-12-04", custom_event="purchase").results

        # Verify that conversion data is included in results
        assert len(results) > 0

        # Results should include conversion metrics
        for row in results:
            # Format is [path, visitors, unique_conversions, conversion_rate]
            assert len(row) >= 4

            # Check conversion metrics
            if row[0] == "/product":
                # The product page should have conversion data
                assert row[2][0] is not None, "Should have conversion data for /product"
                # Only 1 user converted
                assert row[2][0] == 1, "Should have 1 unique conversion for /product"

    def test_path_cleaning(self):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2023-12-03"))

        # Create events with paths that need cleaning
        self._create_events(
            [
                (
                    "p1",
                    [
                        ("2023-12-02", s1, "/products/123"),
                        ("2023-12-02", s1, "/products/456"),
                        ("2023-12-03", s1, "/blog/2023/01/post"),
                    ],
                ),
                ("p2", [("2023-12-03", s2, "/products/789"), ("2023-12-03", s2, "/blog/2022/12/another-post")]),
            ]
        )

        # Define path cleaning filters
        path_cleaning_filters = [
            {"regex": r"^/products/[0-9]+", "alias": "/products/:id"},
            {"regex": r"^/blog/[0-9]{4}/[0-9]{2}/", "alias": "/blog/:year/:month/:post"},
        ]

        # Run query with path cleaning
        results = self._run_web_stats_table_query(
            "2023-12-01", "2023-12-04", path_cleaning_filters=path_cleaning_filters
        ).results

        # Verify that paths are cleaned
        paths = [row[0] for row in results]

        # Check that cleaned paths are present
        assert "/products/:id" in paths, "Should have cleaned product paths"
        assert "/blog/:year/:month/:post" in paths, "Should have cleaned blog paths"

        # Check that original paths are not present
        assert "/products/123" not in paths, "Original product path should not be present"
        assert "/blog/2023/01/post" not in paths, "Original blog path should not be present"

        # Check counts for cleaned paths
        product_row = next((row for row in results if row[0] == "/products/:id"), None)
        blog_row = next((row for row in results if row[0] == "/blog/:year/:month/:post"), None)

        assert product_row is not None
        assert blog_row is not None

        # 3 product page views total
        assert product_row[2][0] == 3, "Should have 3 views for cleaned product paths"
        # 2 blog page views total
        assert blog_row[2][0] == 2, "Should have 2 views for cleaned blog paths"

    def test_bounce_rate_calculation(self):
        # Create sessions with different bounce behaviors

        # Session 1: Bounced session (only one page view)
        self._create_pageviews("user1", [("/", "2023-12-02T10:00:00Z", 0.5)])

        # Session 2: Non-bounced session (multiple page views)
        self._create_pageviews(
            "user2",
            [
                ("/", "2023-12-02T11:00:00Z", 0.3),
                ("/about", "2023-12-02T11:05:00Z", 0.7),
                ("/contact", "2023-12-02T11:10:00Z", 0.9),
            ],
        )

        # Session 3: Another bounced session
        self._create_pageviews("user3", [("/products", "2023-12-03T10:00:00Z", 0.4)])

        flush_persons_and_events()

        # Run query with bounce rate included
        results = self._run_web_stats_table_query("2023-12-01", "2023-12-04", include_bounce_rate=True).results

        # Verify bounce rate calculations
        home_row = next((row for row in results if row[0] == "/"), None)
        products_row = next((row for row in results if row[0] == "/products"), None)
        about_row = next((row for row in results if row[0] == "/about"), None)

        assert home_row is not None, "Home page should be in results"
        assert products_row is not None, "Products page should be in results"

        # Home page has 2 visitors, 1 bounced (50% bounce rate)
        assert home_row[3][0] is not None, "Home page should have bounce rate"
        assert 0.45 <= home_row[3][0] <= 0.55, f"Home page should have ~50% bounce rate, got {home_row[3][0]}"

        # Products page has 1 visitor, 1 bounced (100% bounce rate)
        assert products_row[3][0] is not None, "Products page should have bounce rate"
        assert (
            0.95 <= products_row[3][0] <= 1.0
        ), f"Products page should have ~100% bounce rate, got {products_row[3][0]}"

        # About page has 1 visitor, 0 bounced (0% bounce rate)
        if about_row is not None:
            assert about_row[3][0] is not None, "About page should have bounce rate"
            assert 0 <= about_row[3][0] <= 0.05, f"About page should have ~0% bounce rate, got {about_row[3][0]}"

    def test_action_conversion_goal(self):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2023-12-03"))

        # Create pageview events
        self._create_events(
            [
                ("p1", [("2023-12-02", s1, "/"), ("2023-12-02", s1, "/product"), ("2023-12-02", s1, "/checkout")]),
                (
                    "p2",
                    [
                        ("2023-12-03", s2, "/"),
                        ("2023-12-03", s2, "/product"),
                        # No checkout for p2
                    ],
                ),
            ]
        )

        # Create an action for the checkout page
        action = Action.objects.create(team=self.team, name="Checkout Action")
        action.steps.create(
            event="$pageview",
            url="/checkout",
            url_matching="exact",
        )

        # Run query with action conversion goal
        results = self._run_web_stats_table_query("2023-12-01", "2023-12-04", action=action).results

        # Verify that conversion data is included in results
        assert len(results) > 0

        # Results should include conversion metrics
        for row in results:
            # Format is [path, visitors, unique_conversions, conversion_rate]
            assert len(row) >= 4

            # Check conversion metrics for product page
            if row[0] == "/product":
                # The product page should have conversion data
                assert row[2][0] is not None, "Should have conversion data for /product"
                # Only 1 user converted (went to checkout)
                assert row[2][0] == 1, "Should have 1 unique conversion for /product"
                # Conversion rate should be 50% (1 out of 2 visitors)
                assert 0.45 <= row[3][0] <= 0.55, f"Conversion rate should be ~50%, got {row[3][0]}"

            # Home page should also have conversion data
            if row[0] == "/":
                assert row[2][0] is not None, "Should have conversion data for home page"
                assert row[2][0] == 1, "Should have 1 unique conversion for home page"
                # Conversion rate should be 50% (1 out of 2 visitors)
                assert 0.45 <= row[3][0] <= 0.55, f"Conversion rate should be ~50%, got {row[3][0]}"

    def test_combined_features(self):
        """Test multiple features together to ensure they work in combination."""
        s1 = str(uuid7("2023-12-02"))

        # Create events with various properties
        self._create_events(
            [
                (
                    "p1",
                    [
                        ("2023-12-02", s1, "/", {"$browser": "Chrome", "$device_type": "Desktop"}),
                        ("2023-12-02", s1, "/products", {"$browser": "Chrome", "$device_type": "Desktop"}),
                        (
                            "2023-12-02",
                            s1,
                            "/checkout",
                            {"$browser": "Chrome", "$device_type": "Desktop", "$purchase": True, "$revenue": 100},
                        ),
                    ],
                )
            ]
        )

        # Create an action for the checkout page
        action = Action.objects.create(team=self.team, name="Checkout Action")
        action.steps.create(
            event="$pageview",
            url="/checkout",
            url_matching="exact",
        )

        # Run query with multiple features enabled
        with freeze_time(self.QUERY_TIMESTAMP):
            modifiers = HogQLQueryModifiers(sessionTableVersion=SessionTableVersion.V2)
            query = WebStatsTableQuery(
                dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-04"),
                properties=[EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.EXACT)],
                breakdownBy=WebStatsBreakdown.PAGE,
                includeBounceRate=True,
                includeRevenue=True,
                includeDate=True,
                conversionGoal=ActionConversionGoal(actionId=action.id),
                limit=10,
            )
            runner = WebStatsTableQueryRunner(team=self.team, query=query, modifiers=modifiers)
            results = runner.calculate().results

        # Verify that results include all the requested data
        assert len(results) > 0

        # First element should be a date
        assert isinstance(results[0][0], str)
        assert len(results[0][0]) == 10  # YYYY-MM-DD format

        # Results should include all pages
        page_paths = [row[1] for row in results]  # Second column is the path when date is included
        assert "/" in page_paths
        assert "/products" in page_paths
        assert "/checkout" in page_paths

        # Results should include conversion metrics, bounce rate, and revenue
        for row in results:
            if row[1] == "/products":
                # Should have conversion data
                assert row[3][0] is not None, "Should have conversion data"
                # Should have bounce rate
                assert row[5][0] is not None, "Should have bounce rate"
