import uuid
from freezegun import freeze_time

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.web_preaggregated.sql import WEB_BOUNCES_INSERT_SQL
from posthog.models.utils import uuid7
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
)
from ee.clickhouse.materialized_columns.columns import materialize


class TestWebBouncesWithMaterialized(ClickhouseTestMixin, APIBaseTest):
    def test_web_bounces_full_query_with_argmax_validation(self):
        """Test that the full WEB_BOUNCES_INSERT_SQL query works with materialized columns and validates argMax person_id aggregation, bounce rate, and session duration"""

        # Materialize the columns referenced in the SQL query
        materialize("events", "$host")
        materialize("events", "$device_type")
        materialize("events", "$browser")
        materialize("events", "$os")
        materialize("events", "$viewport_width")
        materialize("events", "$viewport_height")
        materialize("events", "$geoip_country_code")
        materialize("events", "$geoip_city_name")
        materialize("events", "$geoip_subdivision_1_code")
        materialize("events", "$pathname")

        # Session 1: Anonymous -> Identified user (10 minutes, 3 pageviews - NOT a bounce)
        anon1_id = f"anon1_{uuid.uuid4().hex[:8]}"
        user1_id = f"user1_{uuid.uuid4().hex[:8]}"
        _create_person(distinct_ids=[anon1_id], team_id=self.team.pk)
        _create_person(distinct_ids=[user1_id], team_id=self.team.pk)
        session1_id = str(uuid7())

        # Session 2: Single page bounce (0 minutes, 1 pageview - IS a bounce)
        user2_id = f"user2_{uuid.uuid4().hex[:8]}"
        _create_person(distinct_ids=[user2_id], team_id=self.team.pk)
        session2_id = str(uuid7())

        # Session 3: Long multi-page session (15 minutes, 4 pageviews - NOT a bounce)
        user3_id = f"user3_{uuid.uuid4().hex[:8]}"
        _create_person(distinct_ids=[user3_id], team_id=self.team.pk)
        session3_id = str(uuid7())

        # Session 4: Another bounce (0 minutes, 1 pageview - IS a bounce)
        user4_id = f"user4_{uuid.uuid4().hex[:8]}"
        _create_person(distinct_ids=[user4_id], team_id=self.team.pk)
        session4_id = str(uuid7())

        # Session 5: Quick two-page session (2 minutes, 2 pageviews - NOT a bounce)
        user5_id = f"user5_{uuid.uuid4().hex[:8]}"
        _create_person(distinct_ids=[user5_id], team_id=self.team.pk)
        session5_id = str(uuid7())

        # Create Session 1 events: Anonymous -> Identified (10 minutes, 3 pageviews)
        with freeze_time("2024-01-01T10:00:00Z"):
            _create_event(
                distinct_id=anon1_id,
                event="$pageview",
                team=self.team,
                timestamp="2024-01-01T10:00:00Z",
                properties={
                    "$session_id": session1_id,
                    "$current_url": "https://example.com/landing",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                    "$pathname": "/landing",
                },
            )

        with freeze_time("2024-01-01T10:05:00Z"):
            _create_event(
                distinct_id=user1_id,
                event="$pageview",
                team=self.team,
                timestamp="2024-01-01T10:05:00Z",
                properties={
                    "$session_id": session1_id,
                    "$current_url": "https://example.com/signup",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                    "$pathname": "/signup",
                },
            )

        with freeze_time("2024-01-01T10:10:00Z"):
            _create_event(
                distinct_id=user1_id,
                event="$pageview",
                team=self.team,
                timestamp="2024-01-01T10:10:00Z",
                properties={
                    "$session_id": session1_id,
                    "$current_url": "https://example.com/dashboard",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                    "$pathname": "/dashboard",
                },
            )

        # Create Session 2: Single page bounce (0 minutes, 1 pageview)
        with freeze_time("2024-01-01T11:00:00Z"):
            _create_event(
                distinct_id=user2_id,
                event="$pageview",
                team=self.team,
                timestamp="2024-01-01T11:00:00Z",
                properties={
                    "$session_id": session2_id,
                    "$current_url": "https://example.com/landing",
                    "$host": "example.com",
                    "$device_type": "Mobile",
                    "$browser": "Safari",
                    "$os": "iOS",
                    "$viewport_width": 375,
                    "$viewport_height": 812,
                    "$pathname": "/landing",
                },
            )

        # Create Session 3: Long session (15 minutes, 4 pageviews)
        timestamps_3 = ["2024-01-01T12:00:00Z", "2024-01-01T12:05:00Z", "2024-01-01T12:10:00Z", "2024-01-01T12:15:00Z"]
        urls_3 = ["/landing", "/features", "/pricing", "/contact"]
        for _, (ts, url) in enumerate(zip(timestamps_3, urls_3)):
            with freeze_time(ts):
                _create_event(
                    distinct_id=user3_id,
                    event="$pageview",
                    team=self.team,
                    timestamp=ts,
                    properties={
                        "$session_id": session3_id,
                        "$current_url": f"https://example.com{url}",
                        "$host": "example.com",
                        "$device_type": "Desktop",
                        "$browser": "Firefox",
                        "$os": "macOS",
                        "$viewport_width": 1440,
                        "$viewport_height": 900,
                        "$pathname": url,
                    },
                )

        # Create Session 4: Another bounce (0 minutes, 1 pageview)
        with freeze_time("2024-01-01T13:00:00Z"):
            _create_event(
                distinct_id=user4_id,
                event="$pageview",
                team=self.team,
                timestamp="2024-01-01T13:00:00Z",
                properties={
                    "$session_id": session4_id,
                    "$current_url": "https://example.com/pricing",
                    "$host": "example.com",
                    "$device_type": "Tablet",
                    "$browser": "Chrome",
                    "$os": "Android",
                    "$viewport_width": 768,
                    "$viewport_height": 1024,
                    "$pathname": "/pricing",
                },
            )

        # Create Session 5: Quick two-page session (2 minutes, 2 pageviews)
        with freeze_time("2024-01-01T14:00:00Z"):
            _create_event(
                distinct_id=user5_id,
                event="$pageview",
                team=self.team,
                timestamp="2024-01-01T14:00:00Z",
                properties={
                    "$session_id": session5_id,
                    "$current_url": "https://example.com/features",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Edge",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                    "$pathname": "/features",
                },
            )

        with freeze_time("2024-01-01T14:02:00Z"):
            _create_event(
                distinct_id=user5_id,
                event="$pageview",
                team=self.team,
                timestamp="2024-01-01T14:02:00Z",
                properties={
                    "$session_id": session5_id,
                    "$current_url": "https://example.com/signup",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Edge",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                    "$pathname": "/signup",
                },
            )

        flush_persons_and_events()

        sql = WEB_BOUNCES_INSERT_SQL(
            date_start="2024-01-01", date_end="2024-01-02", team_ids=[self.team.pk], select_only=True
        )

        # Note: We can't directly execute the raw WEB_BOUNCES_INSERT_SQL query because it returns
        # aggregate state columns that the ClickHouse Python driver can't deserialize.
        # Instead, we validate the key functionality through the metrics query which processes
        # the full dataset and confirms argMax person_id selection works correctly.

        metrics_sql = f"""
        WITH session_data AS (
            {sql}
        ),
        aggregated AS (
            SELECT
                uniqMerge(persons_uniq_state) AS unique_persons,
                sumMerge(pageviews_count_state) AS total_pageviews,
                uniqMerge(sessions_uniq_state) AS unique_sessions,
                sumMerge(total_session_duration_state) AS total_duration,
                sumMerge(total_session_count_state) AS total_session_count,
                sumMerge(bounces_count_state) AS bounce_sessions
            FROM session_data
        )
        SELECT
            unique_persons,
            total_pageviews,
            unique_sessions,
            if(total_session_count > 0, total_duration / total_session_count, 0) AS avg_session_duration,
            bounce_sessions,
            if(unique_sessions > 0, bounce_sessions / unique_sessions, 0) AS bounce_rate
        FROM aggregated
        """

        metrics_results = sync_execute(metrics_sql)
        assert len(metrics_results) == 1

        metrics = metrics_results[0]
        unique_persons, total_pageviews, unique_sessions, avg_duration, bounce_sessions, bounce_rate = metrics

        # Expected values:
        # Session 1: 10 minutes (600s), 3 pageviews - NOT bounce
        # Session 2: 0 minutes (0s), 1 pageview - IS bounce
        # Session 3: 15 minutes (900s), 4 pageviews - NOT bounce
        # Session 4: 0 minutes (0s), 1 pageview - IS bounce
        # Session 5: 2 minutes (120s), 2 pageviews - NOT bounce

        expected_unique_persons = 5
        expected_total_pageviews = 11  # 3+1+4+1+2 = 11
        expected_unique_sessions = 5
        expected_bounce_sessions = 2  # Sessions 2 and 4
        expected_bounce_rate = 2 / 5  # 0.4 (40%)
        expected_avg_session_duration = (600 + 0 + 900 + 0 + 120) / 5  # 324.0 seconds

        # Validate core metrics
        assert unique_persons == expected_unique_persons
        assert total_pageviews == expected_total_pageviews
        assert unique_sessions == expected_unique_sessions
        assert bounce_sessions == expected_bounce_sessions
        assert abs(bounce_rate - expected_bounce_rate) < 0.01
        assert abs(avg_duration - expected_avg_session_duration) < 1.0
