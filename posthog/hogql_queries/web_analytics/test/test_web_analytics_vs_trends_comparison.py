"""
Test suite demonstrating the differences between Web Analytics queries and Trends queries.

This test file documents why Web Analytics (WebOverview, WebStatsTable) and Trends queries
may return different values for page views and unique users, even when querying the same
$pageview events.

## Key Architectural Differences

### Web Analytics Queries
- Join events with sessions (`session.session_id`)
- Group by `(session_id, breakdown_value)` first, then aggregate
- Session expansion means counting happens at the session level
- Uses `any(person_id)` per session per breakdown - deduplicates within session

### Trends Queries
- Direct event counting without session grouping
- `count()` for total events
- `count(DISTINCT person_id)` for unique users (DAU)
- No session join or intermediate grouping

## When Results Differ

1. **Multiple pageviews in one session on the same path**:
   - Web Analytics: Groups by session first, so multiple pageviews on same path in same session
     count as multiple views but the person is deduplicated per session
   - Trends: Counts each pageview event directly

2. **Session spanning multiple days**:
   - Web Analytics: Session start timestamp determines which period the session belongs to
   - Trends: Each event's timestamp determines which period it belongs to

3. **The JOIN effect**:
   - Web Analytics inner query: `GROUP BY session_id, breakdown_value`
   - This means aggregations happen per-session-per-breakdown first
"""

from datetime import datetime

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)

from parameterized import parameterized

from posthog.schema import (
    BaseMathType,
    ChartDisplayType,
    DateRange,
    EventsNode,
    IntervalType,
    NodeKind,
    TrendsFilter,
    TrendsQuery,
    WebOverviewQuery,
    WebStatsBreakdown,
    WebStatsTableQuery,
)

from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.models.utils import uuid7


class TestWebAnalyticsVsTrendsComparison(ClickhouseTestMixin, APIBaseTest):
    """
    Test suite demonstrating differences between Web Analytics and Trends queries.

    These tests serve as documentation for why the two query systems may return
    different results for seemingly similar metrics.
    """

    QUERY_TIMESTAMP = "2024-01-15"

    def _create_pageview_events(self, data: list[tuple[str, list[tuple[str, str, str]]]]):
        """
        Create pageview events for testing.

        Args:
            data: List of (person_id, [(timestamp, session_id, pathname), ...])
        """
        for person_id, events in data:
            with freeze_time(events[0][0]):
                _create_person(
                    team_id=self.team.pk,
                    distinct_ids=[person_id],
                    properties={"name": person_id},
                )
            for timestamp, session_id, pathname in events:
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=person_id,
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$pathname": pathname,
                        "$current_url": f"https://example.com{pathname}",
                    },
                )

    def _run_web_overview(self, date_from: str, date_to: str):
        """Run WebOverviewQuery and return results."""
        with freeze_time(self.QUERY_TIMESTAMP):
            query = WebOverviewQuery(
                dateRange=DateRange(date_from=date_from, date_to=date_to),
                properties=[],
                compareFilter=None,
            )
            runner = WebOverviewQueryRunner(team=self.team, query=query)
            return runner.calculate()

    def _run_web_stats_table(self, date_from: str, date_to: str):
        """Run WebStatsTableQuery with PAGE breakdown and return results."""
        with freeze_time(self.QUERY_TIMESTAMP):
            query = WebStatsTableQuery(
                dateRange=DateRange(date_from=date_from, date_to=date_to),
                properties=[],
                breakdownBy=WebStatsBreakdown.PAGE,
                compareFilter=None,
            )
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            return runner.calculate()

    def _run_trends_pageview_count(self, date_from: str, date_to: str):
        """Run TrendsQuery for $pageview total count."""
        with freeze_time(self.QUERY_TIMESTAMP):
            query = TrendsQuery(
                dateRange=DateRange(date_from=date_from, date_to=date_to),
                interval=IntervalType.DAY,
                series=[
                    EventsNode(
                        event="$pageview",
                        kind=NodeKind.EVENTS_NODE,
                        math=BaseMathType.TOTAL,
                        name="Pageview",
                    )
                ],
                trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
            )
            runner = TrendsQueryRunner(team=self.team, query=query)
            return runner.calculate()

    def _run_trends_unique_users(self, date_from: str, date_to: str):
        """Run TrendsQuery for $pageview unique users (DAU)."""
        with freeze_time(self.QUERY_TIMESTAMP):
            query = TrendsQuery(
                dateRange=DateRange(date_from=date_from, date_to=date_to),
                interval=IntervalType.DAY,
                series=[
                    EventsNode(
                        event="$pageview",
                        kind=NodeKind.EVENTS_NODE,
                        math=BaseMathType.DAU,
                        name="Pageview",
                    )
                ],
                trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
            )
            runner = TrendsQueryRunner(team=self.team, query=query)
            return runner.calculate()

    def test_single_session_multiple_pageviews_same_path(self):
        """
        Scenario: One person visits the same page multiple times in one session.

        Expected behavior:
        - Web Analytics views: 3 (counts each pageview)
        - Web Analytics visitors: 1 (one unique person)
        - Trends total: 3 (counts each event)
        - Trends DAU: 1 (one unique person)

        In this simple case, both should match.
        """
        session_id = str(uuid7("2024-01-10"))

        self._create_pageview_events(
            [
                (
                    "user1",
                    [
                        ("2024-01-10T10:00:00Z", session_id, "/home"),
                        ("2024-01-10T10:05:00Z", session_id, "/home"),
                        ("2024-01-10T10:10:00Z", session_id, "/home"),
                    ],
                ),
            ]
        )

        web_overview = self._run_web_overview("2024-01-01", "2024-01-14")
        trends_total = self._run_trends_pageview_count("2024-01-01", "2024-01-14")
        trends_dau = self._run_trends_unique_users("2024-01-01", "2024-01-14")

        web_visitors = next(r for r in web_overview.results if r.key == "visitors").value
        web_views = next(r for r in web_overview.results if r.key == "views").value
        trends_total_count = trends_total.results[0]["aggregated_value"]
        trends_unique_users = trends_dau.results[0]["aggregated_value"]

        assert web_views == 3, f"Web Analytics views: expected 3, got {web_views}"
        assert web_visitors == 1, f"Web Analytics visitors: expected 1, got {web_visitors}"
        assert trends_total_count == 3, f"Trends total: expected 3, got {trends_total_count}"
        assert trends_unique_users == 1, f"Trends DAU: expected 1, got {trends_unique_users}"

    def test_multiple_sessions_same_person_same_day(self):
        """
        Scenario: One person has multiple sessions on the same day.

        Expected behavior:
        - Web Analytics sessions: 2 (two distinct sessions)
        - Web Analytics visitors: 1 (one unique person)
        - Trends DAU: 1 (one unique person)

        Web Analytics tracks sessions, Trends does not (unless using unique_session math).
        """
        session1 = str(uuid7("2024-01-10"))
        session2 = str(uuid7("2024-01-10"))

        self._create_pageview_events(
            [
                (
                    "user1",
                    [
                        ("2024-01-10T09:00:00Z", session1, "/home"),
                        ("2024-01-10T09:05:00Z", session1, "/about"),
                        ("2024-01-10T14:00:00Z", session2, "/home"),
                        ("2024-01-10T14:05:00Z", session2, "/pricing"),
                    ],
                ),
            ]
        )

        web_overview = self._run_web_overview("2024-01-01", "2024-01-14")
        trends_dau = self._run_trends_unique_users("2024-01-01", "2024-01-14")

        web_visitors = next(r for r in web_overview.results if r.key == "visitors").value
        web_sessions = next(r for r in web_overview.results if r.key == "sessions").value
        web_views = next(r for r in web_overview.results if r.key == "views").value
        trends_unique_users = trends_dau.results[0]["aggregated_value"]

        assert web_visitors == 1, f"Web Analytics visitors: expected 1, got {web_visitors}"
        assert web_sessions == 2, f"Web Analytics sessions: expected 2, got {web_sessions}"
        assert web_views == 4, f"Web Analytics views: expected 4, got {web_views}"
        assert trends_unique_users == 1, f"Trends DAU: expected 1, got {trends_unique_users}"

    def test_web_stats_table_session_grouping_effect(self):
        """
        Scenario: Multiple pageviews on the same path within one session.

        This test demonstrates the session grouping effect in WebStatsTable.

        The WebStatsTable inner query groups by (session_id, breakdown_value) first:
        ```sql
        SELECT
            any(person_id) AS filtered_person_id,
            count() AS filtered_pageview_count,
            {breakdown_value} AS breakdown_value,
            session.session_id AS session_id,
            ...
        FROM events
        GROUP BY session_id, breakdown_value
        ```

        This means for each (session, path) combination, we get one row with:
        - filtered_person_id: any person from that session (deduplicated)
        - filtered_pageview_count: count of pageviews for that path in that session
        """
        session_id = str(uuid7("2024-01-10"))

        self._create_pageview_events(
            [
                (
                    "user1",
                    [
                        ("2024-01-10T10:00:00Z", session_id, "/home"),
                        ("2024-01-10T10:01:00Z", session_id, "/home"),
                        ("2024-01-10T10:02:00Z", session_id, "/about"),
                        ("2024-01-10T10:03:00Z", session_id, "/about"),
                        ("2024-01-10T10:04:00Z", session_id, "/about"),
                    ],
                ),
            ]
        )

        web_stats = self._run_web_stats_table("2024-01-01", "2024-01-14")
        trends_total = self._run_trends_pageview_count("2024-01-01", "2024-01-14")

        results_by_path = {row[0]: row for row in web_stats.results}

        home_views = results_by_path.get("/home", [None, None, (0, None)])[2][0]
        about_views = results_by_path.get("/about", [None, None, (0, None)])[2][0]
        total_web_views = home_views + about_views

        trends_total_count = trends_total.results[0]["aggregated_value"]

        assert home_views == 2, f"Web Stats /home views: expected 2, got {home_views}"
        assert about_views == 3, f"Web Stats /about views: expected 3, got {about_views}"
        assert total_web_views == 5, f"Web Stats total views: expected 5, got {total_web_views}"
        assert trends_total_count == 5, f"Trends total: expected 5, got {trends_total_count}"

    def test_multiple_users_same_session_id_edge_case(self):
        """
        Edge case: Multiple users somehow share the same session_id.

        This shouldn't happen in practice, but demonstrates how the queries handle it.

        Web Analytics uses `any(person_id)` per session, so only one person would be counted
        per session in the inner grouping. However, the outer uniq() aggregation would
        still correctly count unique persons.

        Trends directly counts unique persons without session grouping.
        """
        shared_session = str(uuid7("2024-01-10"))

        self._create_pageview_events(
            [
                (
                    "user1",
                    [
                        ("2024-01-10T10:00:00Z", shared_session, "/home"),
                    ],
                ),
                (
                    "user2",
                    [
                        ("2024-01-10T10:01:00Z", shared_session, "/home"),
                    ],
                ),
            ]
        )

        web_overview = self._run_web_overview("2024-01-01", "2024-01-14")
        trends_dau = self._run_trends_unique_users("2024-01-01", "2024-01-14")

        web_visitors = next(r for r in web_overview.results if r.key == "visitors").value
        web_views = next(r for r in web_overview.results if r.key == "views").value
        trends_unique_users = trends_dau.results[0]["aggregated_value"]

        assert web_views == 2, f"Web Analytics views: expected 2, got {web_views}"
        assert trends_unique_users == 2, f"Trends DAU: expected 2, got {trends_unique_users}"

        # Web analytics visitors may be 1 or 2 depending on which person any() picks
        assert web_visitors in [1, 2], f"Web Analytics visitors: expected 1 or 2, got {web_visitors}"

    @parameterized.expand(
        [
            ("1_user_1_session_1_pageview", 1, 1, 1),
            ("1_user_1_session_5_pageviews", 1, 5, 1),
            ("1_user_3_sessions_2_pageviews_each", 1, 2, 3),
            ("3_users_1_session_each_1_pageview", 3, 1, 1),
            ("3_users_2_sessions_each_3_pageviews", 3, 3, 2),
        ]
    )
    def test_parameterized_comparison(self, _name, num_users, pageviews_per_session, sessions_per_user):
        """
        Parameterized test comparing Web Analytics and Trends across various scenarios.

        This helps identify patterns in when the two systems agree or disagree.
        """
        events_data = []
        base_time = datetime(2024, 1, 10, 10, 0, 0)

        for user_idx in range(num_users):
            user_id = f"user{user_idx}"
            user_events = []

            for session_idx in range(sessions_per_user):
                session_id = str(uuid7(f"2024-01-10-{user_idx}-{session_idx}"))
                session_start = base_time.replace(hour=10 + session_idx * 2)

                for pv_idx in range(pageviews_per_session):
                    timestamp = session_start.replace(minute=pv_idx * 5)
                    user_events.append(
                        (
                            timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            session_id,
                            "/home",
                        )
                    )

            events_data.append((user_id, user_events))

        self._create_pageview_events(events_data)

        web_overview = self._run_web_overview("2024-01-01", "2024-01-14")
        trends_total = self._run_trends_pageview_count("2024-01-01", "2024-01-14")
        trends_dau = self._run_trends_unique_users("2024-01-01", "2024-01-14")

        web_visitors = next(r for r in web_overview.results if r.key == "visitors").value
        web_views = next(r for r in web_overview.results if r.key == "views").value
        web_sessions = next(r for r in web_overview.results if r.key == "sessions").value
        trends_total_count = trends_total.results[0]["aggregated_value"]
        trends_unique_users = trends_dau.results[0]["aggregated_value"]

        expected_total_pageviews = num_users * sessions_per_user * pageviews_per_session
        expected_unique_users = num_users
        expected_sessions = num_users * sessions_per_user

        assert web_views == expected_total_pageviews, (
            f"Web Analytics views: expected {expected_total_pageviews}, got {web_views}"
        )
        assert trends_total_count == expected_total_pageviews, (
            f"Trends total: expected {expected_total_pageviews}, got {trends_total_count}"
        )

        assert web_visitors == expected_unique_users, (
            f"Web Analytics visitors: expected {expected_unique_users}, got {web_visitors}"
        )
        assert trends_unique_users == expected_unique_users, (
            f"Trends DAU: expected {expected_unique_users}, got {trends_unique_users}"
        )

        assert web_sessions == expected_sessions, (
            f"Web Analytics sessions: expected {expected_sessions}, got {web_sessions}"
        )


@snapshot_clickhouse_queries
class TestWebAnalyticsVsTrendsQuerySnapshots(ClickhouseTestMixin, APIBaseTest):
    """
    Query snapshot tests for Web Analytics vs Trends comparison.

    These tests capture the actual SQL queries generated by each system,
    serving as documentation of the query differences.
    """

    QUERY_TIMESTAMP = "2024-01-15"

    def _create_sample_events(self):
        """Create a standard set of events for snapshot testing."""
        session1 = str(uuid7("2024-01-10"))
        session2 = str(uuid7("2024-01-11"))

        for person_id, events in [
            (
                "user1",
                [
                    ("2024-01-10T10:00:00Z", session1, "/home"),
                    ("2024-01-10T10:05:00Z", session1, "/about"),
                ],
            ),
            (
                "user2",
                [
                    ("2024-01-11T14:00:00Z", session2, "/home"),
                ],
            ),
        ]:
            with freeze_time(events[0][0]):
                _create_person(
                    team_id=self.team.pk,
                    distinct_ids=[person_id],
                    properties={"name": person_id},
                )
            for timestamp, session_id, pathname in events:
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=person_id,
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$pathname": pathname,
                        "$current_url": f"https://example.com{pathname}",
                    },
                )

    def test_snapshot_web_overview_query(self):
        """Snapshot of WebOverviewQuery SQL."""
        self._create_sample_events()

        with freeze_time(self.QUERY_TIMESTAMP):
            query = WebOverviewQuery(
                dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-14"),
                properties=[],
                compareFilter=None,
            )
            runner = WebOverviewQueryRunner(team=self.team, query=query)
            runner.calculate()

    def test_snapshot_web_stats_table_query(self):
        """Snapshot of WebStatsTableQuery SQL with PAGE breakdown."""
        self._create_sample_events()

        with freeze_time(self.QUERY_TIMESTAMP):
            query = WebStatsTableQuery(
                dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-14"),
                properties=[],
                breakdownBy=WebStatsBreakdown.PAGE,
                compareFilter=None,
            )
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            runner.calculate()

    def test_snapshot_trends_total_pageviews_query(self):
        """Snapshot of TrendsQuery for total $pageview count."""
        self._create_sample_events()

        with freeze_time(self.QUERY_TIMESTAMP):
            query = TrendsQuery(
                dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-14"),
                interval=IntervalType.DAY,
                series=[
                    EventsNode(
                        event="$pageview",
                        kind=NodeKind.EVENTS_NODE,
                        math=BaseMathType.TOTAL,
                        name="Pageview",
                    )
                ],
                trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
            )
            runner = TrendsQueryRunner(team=self.team, query=query)
            runner.calculate()

    def test_snapshot_trends_unique_users_query(self):
        """Snapshot of TrendsQuery for unique users (DAU)."""
        self._create_sample_events()

        with freeze_time(self.QUERY_TIMESTAMP):
            query = TrendsQuery(
                dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-14"),
                interval=IntervalType.DAY,
                series=[
                    EventsNode(
                        event="$pageview",
                        kind=NodeKind.EVENTS_NODE,
                        math=BaseMathType.DAU,
                        name="Pageview",
                    )
                ],
                trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
            )
            runner = TrendsQueryRunner(team=self.team, query=query)
            runner.calculate()

    def test_snapshot_trends_unique_sessions_query(self):
        """Snapshot of TrendsQuery for unique sessions."""
        self._create_sample_events()

        with freeze_time(self.QUERY_TIMESTAMP):
            query = TrendsQuery(
                dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-14"),
                interval=IntervalType.DAY,
                series=[
                    EventsNode(
                        event="$pageview",
                        kind=NodeKind.EVENTS_NODE,
                        math=BaseMathType.UNIQUE_SESSION,
                        name="Pageview",
                    )
                ],
                trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
            )
            runner = TrendsQueryRunner(team=self.team, query=query)
            runner.calculate()
