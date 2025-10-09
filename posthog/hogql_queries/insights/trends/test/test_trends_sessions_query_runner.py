from django.test import override_settings

from posthog.hogql_queries.insights.trends.test.test_trends_query_runner import TestTrendsQueryRunner
from posthog.hogql_queries.insights.trends.test.test_trends_sessions_base import TrendsSessionsTestBase
from posthog.models.utils import uuid7
from posthog.schema import (
    BaseMathType,
    BreakdownFilter,
    BreakdownType,
    HogQLQueryModifiers,
    IntervalType,
    PropertyMathType,
    SessionsNode,
    SessionTableVersion,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events


@override_settings(IN_UNIT_TESTING=True)
class TestTrendsSessionsQueryRunner(TrendsSessionsTestBase, ClickhouseTestMixin, APIBaseTest):
    """
    Test suite for SessionsNode in trends queries.

    Inherits from TrendsSessionsTestBase to get the _populate_sessions_from_events helper,
    and from the base test classes to get standard testing infrastructure.

    Uses helper methods from TestTrendsQueryRunner but doesn't inherit to avoid running all tests.
    """

    def _run_trends_query(self, *args, **kwargs):
        """Delegate to TestTrendsQueryRunner helper for convenience."""
        helper = TestTrendsQueryRunner()
        helper.team = self.team
        return helper._run_trends_query(*args, **kwargs)

    def test_sessions_node_bounce_rate_over_time(self):
        """
        Test SessionsNode with bounce rate calculation (avg of $is_bounce) over multiple days.
        This tests the full stack: SessionsNode → aggregation_operations → sessions table.
        """
        # Generate UUIDv7 session IDs
        session_ids = [str(uuid7()) for _ in range(9)]

        # Create sessions with different bounce characteristics
        # Day 1 (2020-01-11): 2 bounced sessions (1 pageview each), 1 non-bounced (2 pageviews) → 66.67% bounce
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"$session_id": session_ids[0], "$current_url": "https://example.com/page1"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user2",
            timestamp="2020-01-11T13:00:00Z",
            properties={"$session_id": session_ids[1], "$current_url": "https://example.com/page1"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user3",
            timestamp="2020-01-11T14:00:00Z",
            properties={"$session_id": session_ids[2], "$current_url": "https://example.com/page1"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user3",
            timestamp="2020-01-11T14:05:00Z",
            properties={"$session_id": session_ids[2], "$current_url": "https://example.com/page2"},
        )

        # Day 2 (2020-01-12): 1 bounced session, 2 non-bounced → 33.33% bounce
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user4",
            timestamp="2020-01-12T12:00:00Z",
            properties={"$session_id": session_ids[3], "$current_url": "https://example.com/page1"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user5",
            timestamp="2020-01-12T13:00:00Z",
            properties={"$session_id": session_ids[4], "$current_url": "https://example.com/page1"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user5",
            timestamp="2020-01-12T13:05:00Z",
            properties={"$session_id": session_ids[4], "$current_url": "https://example.com/page2"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user6",
            timestamp="2020-01-12T14:00:00Z",
            properties={"$session_id": session_ids[5], "$current_url": "https://example.com/page1"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user6",
            timestamp="2020-01-12T14:05:00Z",
            properties={"$session_id": session_ids[5], "$current_url": "https://example.com/page2"},
        )

        # Day 3 (2020-01-13): 0 bounced, 3 non-bounced → 0% bounce
        for i in range(3):
            user_id = f"user{7+i}"
            session_id = session_ids[6+i]
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=user_id,
                timestamp=f"2020-01-13T{12+i}:00:00Z",
                properties={"$session_id": session_id, "$current_url": "https://example.com/page1"},
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=user_id,
                timestamp=f"2020-01-13T{12+i}:05:00Z",
                properties={"$session_id": session_id, "$current_url": "https://example.com/page2"},
            )

        flush_persons_and_events()
        self._populate_sessions_from_events()

        response = self._run_trends_query(
            "2020-01-11",
            "2020-01-13",
            IntervalType.DAY,
            [SessionsNode(math=PropertyMathType.AVG, math_property="$is_bounce")],
        )

        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0]["label"], "sessions")
        self.assertEqual(len(response.results[0]["data"]), 3)

        # Day 1: 2/3 bounced = ~0.667
        self.assertAlmostEqual(response.results[0]["data"][0], 0.667, places=2)
        # Day 2: 1/3 bounced = ~0.333
        self.assertAlmostEqual(response.results[0]["data"][1], 0.333, places=2)
        # Day 3: 0/3 bounced = 0
        self.assertEqual(response.results[0]["data"][2], 0)

    def test_sessions_node_total_count(self):
        """Test SessionsNode with math='total' counts sessions correctly."""
        # Generate UUIDv7 session IDs
        session_ids = [str(uuid7()) for _ in range(5)]

        # Create 3 sessions on 2020-01-11, 2 sessions on 2020-01-12
        for i in range(3):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user{i}",
                timestamp="2020-01-11T12:00:00Z",
                properties={"$session_id": session_ids[i]},
            )

        for i in range(3, 5):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user{i}",
                timestamp="2020-01-12T12:00:00Z",
                properties={"$session_id": session_ids[i]},
            )

        flush_persons_and_events()
        self._populate_sessions_from_events()

        response = self._run_trends_query(
            "2020-01-11",
            "2020-01-12",
            IntervalType.DAY,
            [SessionsNode(math=BaseMathType.TOTAL)],
            hogql_modifiers=HogQLQueryModifiers(sessionTableVersion=SessionTableVersion.V2),
        )

        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0]["label"], "sessions")
        self.assertEqual(response.results[0]["data"], [3, 2])

    def test_sessions_node_dau(self):
        """Test SessionsNode with math='dau' counts unique users correctly."""
        # Generate UUIDv7 session IDs
        session_ids = [str(uuid7()) for _ in range(5)]

        # user1 has 2 sessions on day 1, user2 has 1 session on day 1
        # Day 1 should have DAU = 2
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2020-01-11T10:00:00Z",
            properties={"$session_id": session_ids[0]},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2020-01-11T14:00:00Z",
            properties={"$session_id": session_ids[1]},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user2",
            timestamp="2020-01-11T12:00:00Z",
            properties={"$session_id": session_ids[2]},
        )

        # Day 2: user2 has another session, user3 has 1 session → DAU = 2
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user2",
            timestamp="2020-01-12T12:00:00Z",
            properties={"$session_id": session_ids[3]},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user3",
            timestamp="2020-01-12T13:00:00Z",
            properties={"$session_id": session_ids[4]},
        )

        flush_persons_and_events()
        self._populate_sessions_from_events()

        response = self._run_trends_query(
            "2020-01-11",
            "2020-01-12",
            IntervalType.DAY,
            [SessionsNode(math=BaseMathType.DAU)],
        )

        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0]["data"], [2, 2])

    def test_sessions_node_with_session_property_breakdown(self):
        """Test SessionsNode with breakdown on session properties."""
        # Generate UUIDv7 session IDs
        session_ids = [str(uuid7()) for _ in range(3)]

        # Create sessions with different countries
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"$session_id": session_ids[0], "$geoip_country_code": "US"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user2",
            timestamp="2020-01-11T13:00:00Z",
            properties={"$session_id": session_ids[1], "$geoip_country_code": "GB"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user3",
            timestamp="2020-01-11T14:00:00Z",
            properties={"$session_id": session_ids[2], "$geoip_country_code": "US"},
        )

        flush_persons_and_events()
        self._populate_sessions_from_events()

        response = self._run_trends_query(
            "2020-01-11",
            "2020-01-11",
            IntervalType.DAY,
            [SessionsNode(math=BaseMathType.TOTAL)],
            None,
            BreakdownFilter(breakdown="$geoip_country_code", breakdown_type=BreakdownType.SESSION),
        )

        self.assertEqual(len(response.results), 2)
        # Results should be sorted by count, so US (2 sessions) first, then GB (1 session)
        us_result = next(r for r in response.results if r["breakdown_value"] == "US")
        gb_result = next(r for r in response.results if r["breakdown_value"] == "GB")

        self.assertEqual(us_result["data"], [2])
        self.assertEqual(gb_result["data"], [1])

    def test_sessions_node_with_person_property_breakdown(self):
        """Test SessionsNode with breakdown on person properties."""
        # Generate UUIDv7 session IDs
        session_ids = [str(uuid7()) for _ in range(3)]

        # Create persons with properties
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["user1"],
            properties={"subscription": "pro"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["user2"],
            properties={"subscription": "free"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["user3"],
            properties={"subscription": "pro"},
        )

        # Create sessions
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"$session_id": session_ids[0]},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user2",
            timestamp="2020-01-11T13:00:00Z",
            properties={"$session_id": session_ids[1]},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user3",
            timestamp="2020-01-11T14:00:00Z",
            properties={"$session_id": session_ids[2]},
        )

        flush_persons_and_events()
        self._populate_sessions_from_events()

        response = self._run_trends_query(
            "2020-01-11",
            "2020-01-11",
            IntervalType.DAY,
            [SessionsNode(math=BaseMathType.TOTAL)],
            None,
            BreakdownFilter(breakdown="subscription", breakdown_type=BreakdownType.PERSON),
        )

        self.assertEqual(len(response.results), 2)
        pro_result = next(r for r in response.results if r["breakdown_value"] == "pro")
        free_result = next(r for r in response.results if r["breakdown_value"] == "free")

        self.assertEqual(pro_result["data"], [2])
        self.assertEqual(free_result["data"], [1])
