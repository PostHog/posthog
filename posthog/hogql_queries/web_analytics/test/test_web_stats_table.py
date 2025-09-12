import math
from typing import Optional

import unittest
from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from posthog.schema import (
    ActionConversionGoal,
    BounceRatePageViewMode,
    CompareFilter,
    CustomEventConversionGoal,
    DateRange,
    EventPropertyFilter,
    HogQLQueryModifiers,
    PropertyOperator,
    SessionPropertyFilter,
    SessionTableVersion,
    WebAnalyticsOrderByDirection,
    WebAnalyticsOrderByFields,
    WebStatsBreakdown,
    WebStatsTableQuery,
)

from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.models import Action, Cohort, Element
from posthog.models.utils import uuid7

nan_value = float("nan")


class FloatAwareTestCase(unittest.TestCase):
    def assertEqual(self, first, second, msg=None):
        try:
            self._assertEqualRecursive(first, second)
        except AssertionError as e:
            raise self.failureException(msg or str(e)) from e

    def _assertEqualRecursive(self, a, b, msg=None, path="root"):
        if isinstance(a, float) and isinstance(b, float):
            if math.isnan(a) and math.isnan(b):
                return None
            else:
                self.assertAlmostEqual(first=a, second=b, places=7, msg=f"{msg or ''} Float mismatch at {path}")
        elif isinstance(a, list | tuple) and isinstance(b, list | tuple):
            super().assertEqual(len(a), len(b), f"{msg or ''} Length mismatch at {path}")
            for i, (x, y) in enumerate(zip(a, b)):
                self._assertEqualRecursive(x, y, msg=msg, path=f"{path}[{i}]")
        elif isinstance(a, dict) and isinstance(b, dict):
            super().assertEqual(a.keys(), b.keys(), f"{msg or ''} Dict key mismatch at {path}")
            for k in a:
                self._assertEqualRecursive(a[k], b[k], msg=msg, path=f"{path}[{repr(k)}]")
        else:
            super().assertEqual(a, b, f"{msg or ''} Mismatch at {path}")


@snapshot_clickhouse_queries
class TestWebStatsTableQueryRunner(ClickhouseTestMixin, APIBaseTest, FloatAwareTestCase):
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

        self.assertEqual(
            [
                ["/", (2, None), (2, None), 2 / 3, ""],
                ["/login", (1, None), (1, None), 1 / 3, ""],
            ],
            results,
        )

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
            ["Home", (2, None), (2, None), 2 / 3, ""],
            ["Login", (1, None), (1, None), 1 / 3, ""],
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
            ["/", (2, None), (2, None), 2 / 4, ""],
            ["/docs", (1, None), (1, None), 1 / 4, ""],
            ["/login", (1, None), (1, None), 1 / 4, ""],
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
            ["/", (1, 1), (1, 1), 1 / 2, ""],
            ["/docs", (1, 0), (1, 0), 1 / 2, ""],
            ["/login", (0, 1), (0, 1), 0, ""],
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

        assert [["/", (1.0, None), (1.0, None), 1 / 2, ""], ["/login", (1.0, None), (1.0, None), 1 / 2, ""]] == results

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
        # The visitors fraction should still be 2/3, as there were 3 total users even if only 2 were returned by this query
        assert [
            ["/", (2, None), (2, None), 2 / 3, ""],
        ] == response_1.results
        assert response_1.hasMore is True

        response_2 = self._run_web_stats_table_query("all", "2023-12-15", limit=2)
        assert [
            ["/", (2, None), (2, None), 2 / 3, ""],
            ["/login", (1, None), (1, None), 1 / 3, ""],
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
            ["/cleaned/:id", (2, None), (2, None), 2 / 5, ""],
            ["/cleaned/:id/path/:id", (1, None), (1, None), 1 / 5, ""],
            ["/not-cleaned", (1, None), (1, None), 1 / 5, ""],
            ["/thing_c", (1, None), (1, None), 1 / 5, ""],
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
            ["/cleaned/:id", (2, None), (2, None), 2 / 2, ""],
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
            ["/cleaned/:id", (2, None), (2, None), 2 / 2, ""],
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
            ["/cleaned/:id", (2, None), (2, None), 2 / 2, ""],
        ] == results

    def test_path_cleaning_filters_with_multiple_capture_groups(self):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2023-12-10"))
        s3 = str(uuid7("2023-12-11"))
        s4 = str(uuid7("2023-12-12"))

        self._create_events(
            [
                ("p1", [("2023-12-02", s1, "/item/123/detail/456")]),
                ("p2", [("2023-12-10", s2, "/item/789/detail/101")]),
                ("p3", [("2023-12-11", s3, "/item/999/detail/777")]),
                ("p4", [("2023-12-12", s4, "/other/123/path")]),  # Should not match
            ]
        )

        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            path_cleaning_filters=[
                {"regex": "\\/item\\/(\\d+)\\/detail\\/(\\d+)", "alias": "/item/<id>/detail/<detail_id>"},
            ],
        ).results

        # All matching paths should be grouped under the same alias pattern
        assert [
            ["/item/<id>/detail/<detail_id>", (3.0, None), (3.0, None), 3 / 4, ""],
            ["/other/123/path", (1.0, None), (1.0, None), 1 / 4, ""],
        ] == results

    def test_path_cleaning_filters_applied_in_order(self):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2023-12-10"))
        s3 = str(uuid7("2023-12-11"))
        s4 = str(uuid7("2023-12-12"))
        s5 = str(uuid7("2023-12-13"))

        self._create_events(
            [
                ("p1", [("2023-12-02", s1, "/admin/settings/users")]),  # Should match specific rule first
                ("p2", [("2023-12-10", s2, "/admin/dashboard")]),  # Should match general admin rule
                ("p3", [("2023-12-11", s3, "/user/123/profile")]),  # Should match user rule
                ("p4", [("2023-12-12", s4, "/user/456/settings")]),  # Should match user rule
                ("p5", [("2023-12-13", s5, "/other/path")]),  # Should not match any rule
            ]
        )

        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            path_cleaning_filters=[
                # More specific rule first - should match /admin/settings/* paths
                {"regex": "\\/admin\\/settings\\/.*", "alias": "/admin/settings/<page>"},
                # More general rule second - should match remaining /admin/* paths
                {"regex": "\\/admin\\/.*", "alias": "/admin/<section>"},
                # Another rule for user paths
                {"regex": "\\/user\\/\\d+\\/.*", "alias": "/user/<id>/<page>"},
            ],
        ).results

        # The actual results show that ALL rules are applied in sequence using the previous rule's result as input
        # That is why the general /admin/.* gets two results and we don't see a `/admin/settings/<page>`
        assert [
            ["/admin/<section>", (2.0, None), (2.0, None), 2 / 5, ""],  # Both admin paths matched this general rule
            ["/user/<id>/<page>", (2.0, None), (2.0, None), 2 / 5, ""],  # Both user paths
            ["/other/path", (1.0, None), (1.0, None), 1 / 5, ""],  # unchanged
        ] == results

    def test_path_cleaning_with_order_field_and_baseline_urls(self):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2023-12-03"))
        s3 = str(uuid7("2023-12-04"))
        s4 = str(uuid7("2023-12-05"))

        self._create_events(
            [
                ("p1", [("2023-12-02", s1, "/item/2197346/detail1/11234")]),
                ("p2", [("2023-12-03", s2, "/item/2206728/list/2668776/baseline")]),
                ("p3", [("2023-12-04", s3, "/item/5555/list/6666/spp/insessionForm/7777")]),
                ("p4", [("2023-12-05", s4, "/item/123")]),
            ]
        )

        results = self._run_web_stats_table_query(
            "all",
            "2023-12-06",
            path_cleaning_filters=[
                {
                    "regex": r"/item/(\d+)/list/(\d+)/spp/insessionForm/(\d+)",
                    "alias": "/item/<id>/list/<list_id>/spp/insessionForm/<form>",
                    "order": 0,  # Most specific first
                },
                {"regex": r"/item/(\d+)/detail1/(\d+)", "alias": "/item/<id>/detail1/<consultation>", "order": 1},
                {
                    "regex": r"/item/(\d+)/list/(\d+)",
                    "alias": "/item/<id>/list/<list_id>",
                    "order": 2,  # General list rule - should handle baseline URLs correctly
                },
                {
                    "regex": r"/item/(\d+)",
                    "alias": "/item/<id>",
                    "order": 3,  # Most general last
                },
            ],
        ).results

        expected_results = [
            ["/item/<id>/detail1/<consultation>", (1.0, None), (1.0, None), 1 / 4, ""],
            ["/item/<id>/list/<list_id>/spp/insessionForm/<form>", (1.0, None), (1.0, None), 1 / 4, ""],
            ["/item/<id>/list/<list_id>/baseline", (1.0, None), (1.0, None), 1 / 4, ""],
            ["/item/<id>", (1.0, None), (1.0, None), 1 / 4, ""],
        ]

        assert sorted(results) == sorted(expected_results)

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
            ["/a", (1, 0), (1, 0), (0, None), (0.1, None), (0, None), 1 / 3, ""],
            ["/b", (1, 0), (1, 0), (None, None), (0.2, None), (0, None), 1 / 3, ""],
            ["/c", (1, 0), (1, 0), (None, None), (0.9, None), (1, None), 1 / 3, ""],
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
            ["/a", (3, 0), (4, 0), (1 / 3, None), (0.5, None), (0.5, None), 3 / 7, ""],
            ["/b", (2, 0), (2, 0), (None, None), (0.2, None), (0, None), 2 / 7, ""],
            ["/c", (2, 0), (2, 0), (None, None), (0.9, None), (1, None), 2 / 7, ""],
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
            ["/a", (3, 0), (4, 0), (1 / 3, None), (0.5, None), (0.5, None), 1, ""],
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
            ["/a/:id", (1, 0), (1, 0), (0, None), (0.1, None), (0, None), 1 / 3, ""],
            ["/b/:id", (1, 0), (1, 0), (None, None), (0.2, None), (0, None), 1 / 3, ""],
            ["/c/:id", (1, 0), (1, 0), (None, None), (0.9, None), (1, None), 1 / 3, ""],
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
            ["/a", (1, 0), (1, 0), (0, None), 1 / 3, ""],
            ["/b", (1, 0), (1, 0), (None, None), 1 / 3, ""],
            ["/c", (1, 0), (1, 0), (None, None), 1 / 3, ""],
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
            ["/a", (3, 0), (4, 0), (1 / 3, None), 3 / 7, ""],
            ["/b", (2, 0), (2, 0), (None, None), 2 / 7, ""],
            ["/c", (2, 0), (2, 0), (None, None), 2 / 7, ""],
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
            ["/a", (3, 0), (4, 0), (1 / 3, None), 1, ""],
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
            ["/a/:id", (1, 0), (1, 0), (0, None), 1 / 3, ""],
            ["/b/:id", (1, 0), (1, 0), (None, None), 1 / 3, ""],
            ["/c/:id", (1, 0), (1, 0), (None, None), 1 / 3, ""],
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
            ["/a", (1, None), (3, None), (0, None), 1, ""],
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
            ["/a", (3, None), (8, None), (1 / 3, None), 1, ""],
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
            ["/a", (3, None), (4, None), (1 / 3, None), 3 / 3, ""],
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
            ["/a/:id", (1, None), (3, None), (0, None), 1, ""],
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
            ["google / (none) / (none)", (1, None), (1, None), 1 / 2, ""],
            ["news.ycombinator.com / referral / (none)", (1, None), (1, None), 1 / 2, ""],
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

        assert [["google", (1, None), (1, None), 1 / 2, ""], [None, (1, None), (1, None), 1 / 2, ""]] == results

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

        assert [[None, (1, None), (1, None), 1, ""]] == results

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
        assert [["google", (1, None), (2, None), 1, ""]] == results_session

        # Try this with a query that uses event properties
        results_event = self._run_web_stats_table_query(
            "all",
            "2024-07-31",
            breakdown_by=WebStatsBreakdown.PAGE,
        ).results
        assert [["/path", (1, None), (2, None), 1, ""]] == results_event

        # Try this with a query using the bounce rate
        results_event = self._run_web_stats_table_query(
            "all", "2024-07-31", breakdown_by=WebStatsBreakdown.PAGE, include_bounce_rate=True
        ).results
        assert [["/path", (1, 0), (2, 0), (None, None), 1, ""]] == results_event

        # Try this with a query using the scroll depth
        results_event = self._run_web_stats_table_query(
            "all",
            "2024-07-31",
            breakdown_by=WebStatsBreakdown.PAGE,
            include_bounce_rate=True,
            include_scroll_depth=True,
        ).results
        assert [["/path", (1, 0), (2, 0), (None, None), (None, None), (None, None), 1, ""]] == results_event

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

        assert [["/path", (1, None), (1, None), 1, ""]] == results

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

        assert results == [["/path1", (1, None), (1, None), 1, ""]]

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

        for idx, (timezone_offset, before_session_id, after_session_id) in enumerate(
            [
                (0, str(uuid7(before_date)), str(uuid7(after_date))),  # UTC
                (-330, str(uuid7(before_date)), str(uuid7(after_date))),  # Calcutta UTC+5:30
                (240, str(uuid7(before_date)), str(uuid7(after_date))),  # New York UTC-4
                (180, str(uuid7(before_date)), str(uuid7(after_date))),  # Brasilia UTC-3
            ]
        ):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[timezone_offset],
                properties={"name": before_session_id, "email": f"{timezone_offset}@example.com"},
            )

            # Always one event in the before_date
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=timezone_offset,
                timestamp=before_date,
                properties={
                    "$session_id": before_session_id,
                    "$pathname": f"/path/landing",
                    "$timezone_offset": timezone_offset,
                },
            )

            # Several events in the actual range
            for i in range(idx + 1):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=timezone_offset,
                    timestamp=after_date,
                    properties={
                        "$session_id": after_session_id,
                        "$pathname": f"/path{i}",
                        "$timezone_offset": timezone_offset,
                    },
                )

        results = self._run_web_stats_table_query(
            "2024-07-15",  # Period is since July first, we create some events before that date, and some after
            None,
            breakdown_by=WebStatsBreakdown.TIMEZONE,
        ).results

        # Brasilia UTC-3, New York UTC-4, Calcutta UTC+5:30, UTC
        assert results == [
            [-3, (1, None), (4, None), 1 / 4, ""],
            [-4, (1, None), (3, None), 1 / 4, ""],
            [5.5, (1, None), (2, None), 1 / 4, ""],
            [0, (1, None), (1, None), 1 / 4, ""],
        ]

    def test_timezone_filter_with_invalid_timezone_offset(self):
        date = "2024-07-30"

        for idx, (distinct_id, session_id) in enumerate(
            [
                (None, str(uuid7(date))),
                ("Timezone_not_exists", str(uuid7(date))),
                ("", str(uuid7(date))),
            ]
        ):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[str(distinct_id)],
                properties={"name": session_id, "email": f"{distinct_id}@example.com"},
            )

            for i in range(idx + 1):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=str(distinct_id),
                    timestamp=date,
                    properties={"$session_id": session_id, "$pathname": f"/path{i}", "$timezone_offset": distinct_id},
                )

            results = self._run_web_stats_table_query(
                "all",
                None,
                breakdown_by=WebStatsBreakdown.TIMEZONE,
            ).results

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

        self.assertEqual(
            [["https://www.example.com/foo", (1, None), (0, None), (0, None), (0, None), nan_value, ""]],
            response.results,
        )
        assert [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.total_conversions",
            "context.columns.unique_conversions",
            "context.columns.conversion_rate",
            "context.columns.ui_fill_fraction",
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

        assert [["https://www.example.com/foo", (1, None), (1, None), (1, None), (1, None), 1, ""]] == response.results
        assert [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.total_conversions",
            "context.columns.unique_conversions",
            "context.columns.conversion_rate",
            "context.columns.ui_fill_fraction",
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

        assert [[None, (1, None), (1, None), (1, None), (1, None), 1, ""]] == response.results
        assert [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.total_conversions",
            "context.columns.unique_conversions",
            "context.columns.conversion_rate",
            "context.columns.ui_fill_fraction",
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

        assert [[None, (1, None), (1, None), (1, None), (1, None), 1, ""]] == response.results
        assert [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.total_conversions",
            "context.columns.unique_conversions",
            "context.columns.conversion_rate",
            "context.columns.ui_fill_fraction",
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

        assert [[None, (1, None), (1, None), (1, None), (1, None), 1, ""]] == response.results
        assert [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.total_conversions",
            "context.columns.unique_conversions",
            "context.columns.conversion_rate",
            "context.columns.ui_fill_fraction",
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
            ["https://www.example.com/foo", (2, None), (3, None), (2, None), (1, None), 2 / 2, ""],
            ["https://www.example.com/bar", (2, None), (0, None), (0, None), (0, None), 0 / 2, ""],
        ] == response.results
        assert [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.total_conversions",
            "context.columns.unique_conversions",
            "context.columns.conversion_rate",
            "context.columns.ui_fill_fraction",
            "context.columns.cross_sell",
        ] == response.columns

    def test_bounce_rate_with_multiple_pathname_filters(self):
        self._create_pageviews(
            "user1",
            [
                ("/onboarding/portfolio-selection", "2023-12-02T12:00:00", 0.5),
                ("/", "2023-12-02T12:00:30", 0.3),
            ],
        )

        self._create_pageviews(
            "user2",
            [
                ("/", "2023-12-02T12:00:00", 0.1),
            ],
        )

        self._create_pageviews(
            "user3",
            [
                ("/onboarding/portfolio-selection", "2023-12-02T12:00:00", 0.1),
            ],
        )

        self._create_pageviews(
            "user4",
            [
                ("/onboarding/goals", "2023-12-02T12:00:30", 0.8),
                ("/onboarding/funding", "2023-12-02T12:01:00", 0.9),
            ],
        )

        results = self._run_web_stats_table_query(
            "all",
            "2023-12-15",
            breakdown_by=WebStatsBreakdown.PAGE,
            include_bounce_rate=True,
            properties=[
                EventPropertyFilter(
                    key="$pathname", operator=PropertyOperator.EXACT, value=["/onboarding/portfolio-selection", "/"]
                ),
            ],
        ).results

        assert len(results) == 2

        portfolio_row = next((row for row in results if row[0] == "/onboarding/portfolio-selection"), None)
        home_row = next((row for row in results if row[0] == "/"), None)

        assert portfolio_row is not None
        assert home_row is not None

        assert portfolio_row[3][0] == 0.5  # 50% bounce rate (1 of 2 sessions bounced)
        assert home_row[3][0] == 1.0  # 100% bounce rate (1 of 1 sessions bounced)

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

    @freeze_time("2023-12-15T12:00:00Z")
    def test_can_use_preaggregated_tables_with_channel_type_filter(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-11-01", date_to="2023-11-30"),
            breakdownBy=WebStatsBreakdown.DEVICE_TYPE,
            properties=[SessionPropertyFilter(key="$channel_type", value="Direct", operator="exact", type="session")],
        )
        runner = WebStatsTableQueryRunner(team=self.team, query=query)
        pre_agg_builder = runner.preaggregated_query_builder
        assert pre_agg_builder.can_use_preaggregated_tables()
