from freezegun import freeze_time

from posthog.models.web_preaggregated.sql import WEB_BOUNCES_INSERT_SQL
from posthog.models.utils import uuid7
from posthog.test.base import flush_persons_and_events
from posthog.hogql_queries.web_analytics.test.base import WebAnalyticsPreAggregatedTestBase


class TestWebBouncesWithMaterialized(WebAnalyticsPreAggregatedTestBase):
    def _setup_test_data(self):
        """Set up diverse test scenarios for bounce and session duration validation"""
        # Session 1: Anonymous -> Identified user (10 minutes, 3 pageviews - NOT a bounce)
        self.anon1_id = self._create_test_person("anon1")
        self.user1_id = self._create_test_person("user1")
        self.session1_id = str(uuid7())

        # Session 2: Single page bounce (0 minutes, 1 pageview - IS a bounce)
        self.user2_id = self._create_test_person("user2")
        self.session2_id = str(uuid7())

        # Session 3: Long multi-page session (15 minutes, 4 pageviews - NOT a bounce)
        self.user3_id = self._create_test_person("user3")
        self.session3_id = str(uuid7())

        # Session 4: Another bounce (0 minutes, 1 pageview - IS a bounce)
        self.user4_id = self._create_test_person("user4")
        self.session4_id = str(uuid7())

        # Session 5: Quick two-page session (2 minutes, 2 pageviews - NOT a bounce)
        self.user5_id = self._create_test_person("user5")
        self.session5_id = str(uuid7())

        # Create Session 1 events: Anonymous -> Identified (10 minutes, 3 pageviews)
        with freeze_time("2024-01-01T10:00:00Z"):
            self._create_session_event(
                self.anon1_id, self.session1_id, "2024-01-01T10:00:00Z", "https://example.com/landing"
            )

        with freeze_time("2024-01-01T10:05:00Z"):
            self._create_session_event(
                self.user1_id, self.session1_id, "2024-01-01T10:05:00Z", "https://example.com/signup"
            )

        with freeze_time("2024-01-01T10:10:00Z"):
            self._create_session_event(
                self.user1_id, self.session1_id, "2024-01-01T10:10:00Z", "https://example.com/dashboard"
            )

        # Create Session 2: Single page bounce (0 minutes, 1 pageview)
        with freeze_time("2024-01-01T11:00:00Z"):
            self._create_session_event(
                self.user2_id,
                self.session2_id,
                "2024-01-01T11:00:00Z",
                "https://example.com/landing",
                extra_properties={
                    "$device_type": "Mobile",
                    "$browser": "Safari",
                    "$os": "iOS",
                    "$viewport_width": 375,
                    "$viewport_height": 812,
                },
            )

        # Create Session 3: Long session (15 minutes, 4 pageviews)
        session3_events = [
            ("2024-01-01T12:00:00Z", "https://example.com/landing"),
            ("2024-01-01T12:05:00Z", "https://example.com/features"),
            ("2024-01-01T12:10:00Z", "https://example.com/pricing"),
            ("2024-01-01T12:15:00Z", "https://example.com/contact"),
        ]
        self._create_session_with_events(
            self.user3_id,
            self.session3_id,
            session3_events,
            extra_properties={
                "$device_type": "Desktop",
                "$browser": "Firefox",
                "$os": "macOS",
                "$viewport_width": 1440,
                "$viewport_height": 900,
            },
        )

        # Create Session 4: Another bounce (0 minutes, 1 pageview)
        with freeze_time("2024-01-01T13:00:00Z"):
            self._create_session_event(
                self.user4_id,
                self.session4_id,
                "2024-01-01T13:00:00Z",
                "https://example.com/pricing",
                extra_properties={
                    "$device_type": "Tablet",
                    "$browser": "Chrome",
                    "$os": "Android",
                    "$viewport_width": 768,
                    "$viewport_height": 1024,
                },
            )

        # Create Session 5: Quick two-page session (2 minutes, 2 pageviews)
        session5_events = [
            ("2024-01-01T14:00:00Z", "https://example.com/features"),
            ("2024-01-01T14:02:00Z", "https://example.com/signup"),
        ]
        self._create_session_with_events(
            self.user5_id,
            self.session5_id,
            session5_events,
            extra_properties={"$device_type": "Desktop", "$browser": "Edge", "$os": "Windows"},
        )

        flush_persons_and_events()

    def test_web_bounces_table_web_overview_basic_query(self):
        sql = WEB_BOUNCES_INSERT_SQL(
            date_start="2024-01-01", date_end="2024-01-02", team_ids=[self.team.pk], select_only=True
        )

        actual_metrics = self._execute_metrics_query(sql)

        unique_persons, total_pageviews, unique_sessions, avg_duration, bounce_sessions, bounce_rate = actual_metrics

        assert unique_persons == 5
        assert total_pageviews == 11  # 3+1+4+1+2 = 11
        assert unique_sessions == 5
        assert bounce_sessions == 2  # Sessions 2 and 4
        assert abs(bounce_rate - 0.4) < 0.01  # 2/5 = 0.4
        assert abs(avg_duration - 324.0) < 1.0  # (600 + 0 + 900 + 0 + 120) / 5 = 324.0
