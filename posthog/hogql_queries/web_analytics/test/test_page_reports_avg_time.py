from collections import defaultdict
from dataclasses import dataclass

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

import numpy as np
from parameterized import parameterized

from posthog.schema import (
    DateRange,
    EventsNode,
    IntervalType,
    PropertyFilterType,
    PropertyMathType,
    PropertyOperator,
    TrendsQuery,
)

from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.models.utils import uuid7


@dataclass
class PageViewProperties:
    pathname: str
    timestamp: str
    scroll: float = 0
    duration: float | None = 0


class TestPageReportsTimeOnPage(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-12-29"

    def _calculate_pageview_statistics(self, groups_of_pageviews: list[list[PageViewProperties]]):
        per_path_durations: defaultdict[str, list[float | None]] = defaultdict(list)
        total_view_counts: defaultdict[str, int] = defaultdict(int)

        for session_pageviews in groups_of_pageviews:
            for page_view in session_pageviews:
                per_path_durations[page_view.pathname].append(page_view.duration)
                total_view_counts[page_view.pathname] += 1

        def calculate_p90(values: list[float | None]) -> float | None:
            filtered_values = [v for v in values if v is not None]

            if len(filtered_values) == 0:
                return None

            return float(np.percentile(filtered_values, 90))

        results = {}
        for path, durations in per_path_durations.items():
            results[path] = {
                "session_count": len(groups_of_pageviews),
                "view_count": total_view_counts[path],
                "p90_duration": calculate_p90(durations),
            }

        return results

    def _create_pageviews(self, distinct_id: str, list_page_view_properties: list[PageViewProperties]):
        person_time = list_page_view_properties[0].timestamp

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
            prev_page_view_properties: PageViewProperties | None = None

            for page_view in list_page_view_properties:
                prev_pathname = prev_page_view_properties.pathname if prev_page_view_properties else None
                prev_scroll = prev_page_view_properties.scroll if prev_page_view_properties else None
                prev_duration = prev_page_view_properties.duration if prev_page_view_properties else None

                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=distinct_id,
                    timestamp=page_view.timestamp,
                    properties={
                        "$session_id": session_id,
                        "$pathname": page_view.pathname,
                        "$current_url": "http://www.example.com" + page_view.pathname,
                        "$prev_pageview_pathname": prev_pathname,
                        "$prev_pageview_duration": prev_duration,
                        "$prev_pageview_max_scroll_percentage": prev_scroll,
                        "$prev_pageview_max_content_percentage": prev_scroll,
                    },
                )
                prev_page_view_properties = page_view

            if prev_page_view_properties:
                _create_event(
                    team=self.team,
                    event="$pageleave",
                    distinct_id=distinct_id,
                    timestamp=prev_page_view_properties.timestamp,
                    properties={
                        "$session_id": session_id,
                        "$pathname": prev_page_view_properties.pathname,
                        "$current_url": "http://www.example.com" + prev_page_view_properties.pathname,
                        "$prev_pageview_pathname": prev_page_view_properties.pathname,
                        "$prev_pageview_duration": prev_page_view_properties.duration,
                        "$prev_pageview_max_scroll_percentage": prev_page_view_properties.scroll,
                        "$prev_pageview_max_content_percentage": prev_page_view_properties.scroll,
                    },
                )
        return person_result

    def _create_p90_time_on_page_trends_query(
        self,
        pathname: str,
        date_from: str,
        date_to: str,
        interval: IntervalType = IntervalType.DAY,
    ) -> TrendsQuery:
        return TrendsQuery(
            series=[
                EventsNode(
                    math=PropertyMathType.P90,
                    math_property="$prev_pageview_duration",
                    properties=[
                        {
                            "type": PropertyFilterType.EVENT_METADATA,
                            "key": "event",
                            "operator": PropertyOperator.IN_,
                            "value": ["$pageview", "$pageleave", "$screen"],
                        },
                        {
                            "type": PropertyFilterType.EVENT,
                            "key": "$prev_pageview_pathname",
                            "operator": PropertyOperator.EXACT,
                            "value": pathname,
                        },
                        {
                            "type": PropertyFilterType.EVENT,
                            "key": "$prev_pageview_duration",
                            "operator": PropertyOperator.IS_SET,
                            "value": PropertyOperator.IS_SET,
                        },
                    ],
                ),
            ],
            interval=interval,
            dateRange=DateRange(date_from=date_from, date_to=date_to),
        )

    def _run_p90_time_query(
        self, pathname: str, date_from: str, date_to: str, interval: IntervalType = IntervalType.DAY
    ):
        flush_persons_and_events()
        query = self._create_p90_time_on_page_trends_query(pathname, date_from, date_to, interval)
        runner = TrendsQueryRunner(team=self.team, query=query)
        return runner.calculate()

    def test_single_session_p90_all_durations(self):
        page_views = [
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:00", duration=10),
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:10", duration=5),
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:20", duration=30),
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:30", duration=60),
        ]

        self._create_pageviews("p1", page_views)

        stats = self._calculate_pageview_statistics([page_views])

        with freeze_time(self.QUERY_TIMESTAMP):
            response = self._run_p90_time_query("/a", "all", "2025-12-15")

        result_data = response.results[0]["data"]

        self.assertAlmostEqual(result_data[0], stats["/a"]["p90_duration"], places=2)
        self.assertAlmostEqual(stats["/a"]["p90_duration"], 51.0, places=2)

    def test_multiple_sessions_p90_across_all_durations(self):
        p1_page_views = [
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:00", duration=30),
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:10", duration=20),
        ]
        p2_page_views = [
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:20", duration=60),
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:30", duration=40),
        ]
        p3_page_views = [
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:40", duration=10),
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:50", duration=15),
        ]

        self._create_pageviews("p1", p1_page_views)
        self._create_pageviews("p2", p2_page_views)
        self._create_pageviews("p3", p3_page_views)

        stats = self._calculate_pageview_statistics([p1_page_views, p2_page_views, p3_page_views])

        with freeze_time(self.QUERY_TIMESTAMP):
            response = self._run_p90_time_query("/a", "all", "2025-12-15")

        result_data = response.results[0]["data"]

        self.assertAlmostEqual(result_data[0], stats["/a"]["p90_duration"], places=2)
        self.assertAlmostEqual(stats["/a"]["p90_duration"], 50.0, places=2)

    def test_only_sessions_visiting_path_affect_p90(self):
        p1_page_views = [
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:00", duration=25),
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:25", duration=40),
        ]
        p2_page_views = [
            PageViewProperties(pathname="/b", timestamp="2025-12-02T12:01:00", duration=100),
            PageViewProperties(pathname="/b", timestamp="2025-12-02T12:02:40", duration=200),
        ]
        p3_page_views = [
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:03:00", duration=17),
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:03:17", duration=28),
        ]

        self._create_pageviews("p1", p1_page_views)
        self._create_pageviews("p2", p2_page_views)
        self._create_pageviews("p3", p3_page_views)

        stats = self._calculate_pageview_statistics([p1_page_views, p2_page_views, p3_page_views])

        with freeze_time(self.QUERY_TIMESTAMP):
            response = self._run_p90_time_query("/a", "all", "2025-12-15")

        result_data = response.results[0]["data"]

        self.assertAlmostEqual(result_data[0], stats["/a"]["p90_duration"], places=2)
        self.assertAlmostEqual(stats["/a"]["p90_duration"], 36.4, places=2)

    def test_multiple_paths_in_session_p90(self):
        p1_page_views = [
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:00", duration=30),
            PageViewProperties(pathname="/b", timestamp="2025-12-02T12:00:30", duration=20),
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:50", duration=10),
        ]
        p2_page_views = [
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:30", duration=10),
            PageViewProperties(pathname="/c", timestamp="2025-12-02T12:00:40", duration=40),
        ]
        p3_page_views = [
            PageViewProperties(pathname="/b", timestamp="2025-12-02T12:00:50", duration=10),
            PageViewProperties(pathname="/c", timestamp="2025-12-02T12:01:00", duration=15),
        ]
        p4_page_views = [
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:00", duration=40),
            PageViewProperties(pathname="/b", timestamp="2025-12-02T12:00:40", duration=25),
            PageViewProperties(pathname="/c", timestamp="2025-12-02T12:01:50", duration=13),
        ]

        self._create_pageviews("p1", p1_page_views)
        self._create_pageviews("p2", p2_page_views)
        self._create_pageviews("p3", p3_page_views)
        self._create_pageviews("p4", p4_page_views)

        stats = self._calculate_pageview_statistics([p1_page_views, p2_page_views, p3_page_views, p4_page_views])

        with freeze_time(self.QUERY_TIMESTAMP):
            response = self._run_p90_time_query("/a", "all", "2025-12-15")

        result_data = response.results[0]["data"]

        self.assertAlmostEqual(result_data[0], stats["/a"]["p90_duration"], places=2)
        self.assertAlmostEqual(stats["/a"]["p90_duration"], 37.0, places=2)

    def test_no_results_for_nonexistent_pathname(self):
        page_views = [
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:00", duration=10),
        ]
        self._create_pageviews("p1", page_views)
        flush_persons_and_events()

        with freeze_time(self.QUERY_TIMESTAMP):
            response = self._run_p90_time_query("/nonexistent", "all", "2025-12-15")

        result_data = response.results[0]["data"]

        for result in result_data:
            self.assertEqual(result, 0.0)

    def test_multiple_days_groups_by_period_p90(self):
        p1_day1 = [
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:00", duration=10),
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:10", duration=20),
        ]
        p2_day1 = [
            PageViewProperties(pathname="/a", timestamp="2025-12-02T14:00:00", duration=30),
        ]
        p1_day2 = [
            PageViewProperties(pathname="/a", timestamp="2025-12-03T12:00:00", duration=100),
            PageViewProperties(pathname="/a", timestamp="2025-12-03T12:01:40", duration=50),
        ]

        self._create_pageviews("p1", p1_day1)
        self._create_pageviews("p2", p2_day1)
        self._create_pageviews("p1b", p1_day2)

        day1_stats = self._calculate_pageview_statistics([p1_day1, p2_day1])
        day2_stats = self._calculate_pageview_statistics([p1_day2])

        with freeze_time(self.QUERY_TIMESTAMP):
            response = self._run_p90_time_query("/a", "all", "2025-12-15")

        result_data = response.results[0]["data"]

        self.assertAlmostEqual(result_data[0], day1_stats["/a"]["p90_duration"], places=2)
        self.assertAlmostEqual(result_data[1], day2_stats["/a"]["p90_duration"], places=2)

    @parameterized.expand([IntervalType.DAY, IntervalType.WEEK, IntervalType.MONTH])
    def test_interval_grouping_p90(self, interval: IntervalType):
        page_views = [
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:00", duration=10),
        ]
        self._create_pageviews("p1", page_views)
        flush_persons_and_events()

        stats = self._calculate_pageview_statistics([page_views])

        with freeze_time(self.QUERY_TIMESTAMP):
            response = self._run_p90_time_query("/a", "all", "2025-12-15", interval=interval)

        result_data = response.results[0]["data"]

        self.assertAlmostEqual(result_data[0], stats["/a"]["p90_duration"], places=2)

    def test_null_prev_pageview_duration_excluded_from_p90(self):
        p1_page_views = [
            PageViewProperties(pathname="/start", timestamp="2025-12-02T12:00:00", duration=None),
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:01:40", duration=50),
        ]
        p2_page_views = [
            PageViewProperties(pathname="/start", timestamp="2025-12-02T12:02:00", duration=80),
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:03:20", duration=50),
        ]
        p3_page_views = [
            PageViewProperties(pathname="/start", timestamp="2025-12-02T12:04:00", duration=60),
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:05:00", duration=50),
        ]
        p4_page_views = [
            PageViewProperties(pathname="/start", timestamp="2025-12-02T12:06:00", duration=40),
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:06:40", duration=50),
        ]

        self._create_pageviews("p1", p1_page_views)
        self._create_pageviews("p2", p2_page_views)
        self._create_pageviews("p3", p3_page_views)
        self._create_pageviews("p4", p4_page_views)

        stats = self._calculate_pageview_statistics([p1_page_views, p2_page_views, p3_page_views, p4_page_views])

        with freeze_time(self.QUERY_TIMESTAMP):
            response = self._run_p90_time_query("/start", "all", "2025-12-15")

        result_data = response.results[0]["data"]

        self.assertAlmostEqual(result_data[0], stats["/start"]["p90_duration"], places=2)
