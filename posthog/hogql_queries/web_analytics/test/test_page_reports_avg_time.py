from collections import defaultdict
from dataclasses import dataclass

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import DateRange, HogQLFilters, HogQLQuery

from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.models.utils import uuid7


@dataclass
class PageViewProperties:
    pathname: str
    timestamp: str
    scroll: float = 0
    duration: float = 0


class TestPageReportsAvgTimeOnPage(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-12-29"

    def _calculate_pageview_statistics(self, groups_of_pageviews: list[list[PageViewProperties]]):
        per_path_session_avgs: defaultdict[str, list[float]] = defaultdict(list)
        total_view_counts: defaultdict[str, int] = defaultdict(int)

        for session_pageviews in groups_of_pageviews:
            session_totals: defaultdict[str, dict[str, int | float]] = defaultdict(
                lambda: {"count": 0, "duration_sum": 0.0}
            )

            for page_view in session_pageviews:
                entry = session_totals[page_view.pathname]
                entry["count"] += 1
                entry["duration_sum"] += page_view.duration
                total_view_counts[page_view.pathname] += 1

            for path, vals in session_totals.items():
                session_avg = vals["duration_sum"] / vals["count"]
                per_path_session_avgs[path].append(session_avg)

        results = {}
        for path, session_avgs in per_path_session_avgs.items():
            results[path] = {
                "session_count": len(session_avgs),
                "view_count": total_view_counts[path],
                "avg_duration": sum(session_avgs) / len(session_avgs),
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

    def _create_avg_time_on_page_query(
        self,
        pathname: str,
        date_from: str,
        date_to: str,
        interval: str = "day",
    ) -> HogQLQuery:
        interval_functions = {
            "second": "toStartOfSecond",
            "minute": "toStartOfMinute",
            "hour": "toStartOfHour",
            "day": "toStartOfDay",
            "week": "toStartOfWeek",
            "month": "toStartOfMonth",
        }
        interval_fn = interval_functions.get(interval, "toStartOfDay")

        return HogQLQuery(
            query=f"""
SELECT
    {interval_fn}(ts) as period,
    avg(session_avg_duration) as avg_time_on_page
FROM (
    SELECT
        session.session_id as session_id,
        min(session.$start_timestamp) as ts,
        avg(toFloat(events.properties.$prev_pageview_duration)) as session_avg_duration
    FROM events
    WHERE
        events.event IN ('$pageview', '$pageleave', '$screen')
        AND events.properties.$prev_pageview_pathname = {{pathname}}
    GROUP BY session.session_id
)
GROUP BY period
ORDER BY period""",
            filters=HogQLFilters(
                dateRange=DateRange(date_from=date_from, date_to=date_to),
            ),
            values={
                "pathname": pathname,
            },
        )

    def _run_avg_time_query(self, pathname: str, date_from: str, date_to: str, interval: str = "day"):
        query = self._create_avg_time_on_page_query(pathname, date_from, date_to, interval)
        runner = HogQLQueryRunner(team=self.team, query=query)
        return runner.calculate()

    def test_single_session_averages_all_durations(self):
        page_views = [
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:00", duration=10),
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:10", duration=5),
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:20", duration=30),
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:30", duration=60),
        ]

        self._create_pageviews("p1", page_views)
        flush_persons_and_events()

        stats = self._calculate_pageview_statistics([page_views])

        with freeze_time(self.QUERY_TIMESTAMP):
            response = self._run_avg_time_query("/a", "all", "2025-12-15")

        assert len(response.results) == 1
        assert response.results[0][1] == stats["/a"]["avg_duration"]
        assert stats["/a"]["avg_duration"] == (10 + 5 + 30 + 60) / 4

    def test_multiple_sessions_averages_per_session_then_across(self):
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
        flush_persons_and_events()

        stats = self._calculate_pageview_statistics([p1_page_views, p2_page_views, p3_page_views])

        with freeze_time(self.QUERY_TIMESTAMP):
            response = self._run_avg_time_query("/a", "all", "2025-12-15")

        assert len(response.results) == 1
        self.assertAlmostEqual(response.results[0][1], stats["/a"]["avg_duration"], places=2)
        self.assertAlmostEqual(stats["/a"]["avg_duration"], 29.166666, places=2)

    def test_only_sessions_visiting_path_affect_average(self):
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
        flush_persons_and_events()

        stats = self._calculate_pageview_statistics([p1_page_views, p2_page_views, p3_page_views])

        with freeze_time(self.QUERY_TIMESTAMP):
            response = self._run_avg_time_query("/a", "all", "2025-12-15")

        assert len(response.results) == 1
        assert response.results[0][1] == stats["/a"]["avg_duration"]
        assert stats["/a"]["avg_duration"] == 27.5

    def test_multiple_paths_in_session(self):
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
        flush_persons_and_events()

        stats = self._calculate_pageview_statistics([p1_page_views, p2_page_views, p3_page_views, p4_page_views])

        with freeze_time(self.QUERY_TIMESTAMP):
            response = self._run_avg_time_query("/a", "all", "2025-12-15")

        assert len(response.results) == 1
        self.assertAlmostEqual(response.results[0][1], stats["/a"]["avg_duration"], places=2)
        self.assertAlmostEqual(stats["/a"]["avg_duration"], 23.33, places=2)

    def test_no_results_for_nonexistent_pathname(self):
        page_views = [
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:00", duration=10),
        ]
        self._create_pageviews("p1", page_views)
        flush_persons_and_events()

        with freeze_time(self.QUERY_TIMESTAMP):
            response = self._run_avg_time_query("/nonexistent", "all", "2025-12-15")

        assert len(response.results) == 0

    def test_multiple_days_groups_by_period(self):
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
        flush_persons_and_events()

        day1_stats = self._calculate_pageview_statistics([p1_day1, p2_day1])
        day2_stats = self._calculate_pageview_statistics([p1_day2])

        with freeze_time(self.QUERY_TIMESTAMP):
            response = self._run_avg_time_query("/a", "all", "2025-12-15")

        assert len(response.results) == 2
        self.assertAlmostEqual(response.results[0][1], day1_stats["/a"]["avg_duration"], places=2)
        self.assertAlmostEqual(response.results[1][1], day2_stats["/a"]["avg_duration"], places=2)

    @parameterized.expand(["day", "week", "month"])
    def test_interval_grouping(self, interval: str):
        page_views = [
            PageViewProperties(pathname="/a", timestamp="2025-12-02T12:00:00", duration=10),
        ]
        self._create_pageviews("p1", page_views)
        flush_persons_and_events()

        with freeze_time(self.QUERY_TIMESTAMP):
            response = self._run_avg_time_query("/a", "all", "2025-12-15", interval=interval)

        assert len(response.results) >= 1
        assert response.results[0][1] == 10.0
