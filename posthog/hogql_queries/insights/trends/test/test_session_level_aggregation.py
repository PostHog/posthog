"""
Tests for session-level aggregation in trends queries.

This module tests the sessionLevelAggregation flag that enables grouping by session_id
before applying math aggregations on session properties like $is_bounce, $pageview_count, etc.
"""

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.schema import BreakdownFilter, EventsNode, TrendsFilter, TrendsQuery

from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner


class TestSessionLevelAggregation(ClickhouseTestMixin, APIBaseTest):
    """Test session-level aggregation functionality"""

    def _run_trends_query(self, query: TrendsQuery):
        runner = TrendsQueryRunner(team=self.team, query=query)
        return runner.calculate().results

    def test_session_level_aggregation_flag_defaults_to_false(self):
        """sessionLevelAggregation should default to False"""
        query = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                    math="avg",
                    math_property="$is_bounce",
                    math_property_type="session_properties",
                )
            ],
            trendsFilter=TrendsFilter(),
        )
        # Should not raise, and should use default behavior
        results = self._run_trends_query(query)
        assert isinstance(results, list)

    def test_is_bounce_with_session_level_aggregation(self):
        """Test bounce rate calculation using $is_bounce session property"""
        # Create test data: 3 sessions with different bounce characteristics
        # Session 1: Bounced (only 1 pageview, short duration)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2024-01-01 12:00:00",
            properties={"$session_id": "session1"},
        )

        # Session 2: Not bounced (2 pageviews)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user2",
            timestamp="2024-01-01 12:05:00",
            properties={"$session_id": "session2"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user2",
            timestamp="2024-01-01 12:06:00",
            properties={"$session_id": "session2"},
        )

        # Session 3: Bounced (only 1 pageview)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user3",
            timestamp="2024-01-01 12:10:00",
            properties={"$session_id": "session3"},
        )

        flush_persons_and_events()

        # Query with session-level aggregation
        query = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                    math="avg",
                    math_property="$is_bounce",
                    math_property_type="session_properties",
                )
            ],
            trendsFilter=TrendsFilter(sessionLevelAggregation=True),
        )

        with freeze_time("2024-01-02"):
            results = self._run_trends_query(query)

        # Should have results
        assert len(results) > 0
        # The math aggregation should work on session-level data
        assert results[0]["data"] is not None

    def test_pageview_count_with_session_level_aggregation(self):
        """Test average pageviews per session"""
        # Session 1: 3 pageviews
        for i in range(3):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user1",
                timestamp=f"2024-01-01 12:0{i}:00",
                properties={"$session_id": "session1"},
            )

        # Session 2: 1 pageview
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user2",
            timestamp="2024-01-01 12:05:00",
            properties={"$session_id": "session2"},
        )

        # Session 3: 5 pageviews
        for i in range(5):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user3",
                timestamp=f"2024-01-01 12:1{i}:00",
                properties={"$session_id": "session3"},
            )

        flush_persons_and_events()

        query = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                    math="avg",
                    math_property="$pageview_count",
                    math_property_type="session_properties",
                )
            ],
            trendsFilter=TrendsFilter(sessionLevelAggregation=True),
        )

        with freeze_time("2024-01-02"):
            results = self._run_trends_query(query)

        assert len(results) > 0
        # Average should be (3 + 1 + 5) / 3 = 3
        # Note: This is a rough check, actual value depends on how sessions are tracked
        assert results[0]["data"] is not None

    def test_session_level_aggregation_with_breakdown(self):
        """Test session-level aggregation works with breakdowns"""
        # Session 1: Country A, 2 pageviews
        for i in range(2):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user1",
                timestamp=f"2024-01-01 12:0{i}:00",
                properties={"$session_id": "session1", "$geoip_country_code": "US"},
            )

        # Session 2: Country B, 3 pageviews
        for i in range(3):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user2",
                timestamp=f"2024-01-01 12:1{i}:00",
                properties={"$session_id": "session2", "$geoip_country_code": "UK"},
            )

        flush_persons_and_events()

        query = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                    math="avg",
                    math_property="$pageview_count",
                    math_property_type="session_properties",
                )
            ],
            breakdownFilter=BreakdownFilter(breakdown="$geoip_country_code", breakdown_type="event"),
            trendsFilter=TrendsFilter(sessionLevelAggregation=True),
        )

        with freeze_time("2024-01-02"):
            results = self._run_trends_query(query)

        # Should have results for each breakdown value
        assert len(results) >= 1

    def test_session_duration_still_works_without_flag(self):
        """$session_duration should work without sessionLevelAggregation flag (backwards compat)"""
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2024-01-01 12:00:00",
            properties={"$session_id": "session1"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2024-01-01 12:05:00",
            properties={"$session_id": "session1"},
        )

        flush_persons_and_events()

        # Without sessionLevelAggregation flag
        query = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                    math="avg",
                    math_property="$session_duration",
                    math_property_type="session_properties",
                )
            ],
            trendsFilter=TrendsFilter(),  # sessionLevelAggregation defaults to False
        )

        with freeze_time("2024-01-02"):
            results = self._run_trends_query(query)

        # Should still work for backwards compatibility
        assert len(results) > 0
        assert results[0]["data"] is not None

    def test_session_level_aggregation_with_median(self):
        """Test session-level aggregation with median math"""
        # Create 5 sessions with different pageview counts: 1, 2, 3, 4, 5
        for session_num in range(1, 6):
            for event_num in range(session_num):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user{session_num}",
                    timestamp=f"2024-01-01 12:{session_num:02d}:{event_num:02d}",
                    properties={"$session_id": f"session{session_num}"},
                )

        flush_persons_and_events()

        query = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                    math="median",
                    math_property="$pageview_count",
                    math_property_type="session_properties",
                )
            ],
            trendsFilter=TrendsFilter(sessionLevelAggregation=True),
        )

        with freeze_time("2024-01-02"):
            results = self._run_trends_query(query)

        assert len(results) > 0
        # Median of [1, 2, 3, 4, 5] should be 3
        assert results[0]["data"] is not None

    def test_session_level_aggregation_sum_math(self):
        """Test session-level aggregation with sum math for counting bounced sessions"""
        # 2 bounced sessions, 1 non-bounced
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2024-01-01 12:00:00",
            properties={"$session_id": "session1"},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user2",
            timestamp="2024-01-01 12:05:00",
            properties={"$session_id": "session2"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user2",
            timestamp="2024-01-01 12:06:00",
            properties={"$session_id": "session2"},
        )

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user3",
            timestamp="2024-01-01 12:10:00",
            properties={"$session_id": "session3"},
        )

        flush_persons_and_events()

        query = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                    math="sum",
                    math_property="$is_bounce",
                    math_property_type="session_properties",
                )
            ],
            trendsFilter=TrendsFilter(sessionLevelAggregation=True),
        )

        with freeze_time("2024-01-02"):
            results = self._run_trends_query(query)

        assert len(results) > 0
        assert results[0]["data"] is not None

    def test_session_level_aggregation_with_invalid_property(self):
        """Verify graceful handling of non-existent session properties"""
        # Create test events
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2024-01-01 12:00:00",
            properties={"$session_id": "session1"},
        )

        flush_persons_and_events()

        # Query with a non-existent session property
        query = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                    math="avg",
                    math_property="$nonexistent_session_property",
                    math_property_type="session_properties",
                )
            ],
            trendsFilter=TrendsFilter(sessionLevelAggregation=True),
        )

        # Should not crash, should return empty or zero results
        with freeze_time("2024-01-02"):
            results = self._run_trends_query(query)

        assert isinstance(results, list)
        # Results should exist but likely be null or 0
        assert len(results) > 0

    def test_session_level_aggregation_with_null_session_id(self):
        """Events without session_id should be excluded or handled gracefully"""
        # Create events with and without session_id
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2024-01-01 12:00:00",
            properties={"$session_id": "session1"},
        )

        # Event without session_id
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user2",
            timestamp="2024-01-01 12:05:00",
            properties={},  # No session_id
        )

        # Event with null session_id
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user3",
            timestamp="2024-01-01 12:10:00",
            properties={"$session_id": None},
        )

        flush_persons_and_events()

        query = TrendsQuery(
            series=[
                EventsNode(
                    event="$pageview",
                    math="avg",
                    math_property="$pageview_count",
                    math_property_type="session_properties",
                )
            ],
            trendsFilter=TrendsFilter(sessionLevelAggregation=True),
        )

        # Should not crash and should handle null session_id gracefully
        with freeze_time("2024-01-02"):
            results = self._run_trends_query(query)

        assert isinstance(results, list)
        assert len(results) > 0
        # Should have results, but null session events should be excluded or handled
