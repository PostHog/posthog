import uuid
from abc import ABC, abstractmethod
from typing import Optional
from freezegun import freeze_time

from posthog.clickhouse.client.execute import sync_execute
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
)
from ee.clickhouse.materialized_columns.columns import materialize


class WebAnalyticsPreAggregatedTestBase(ClickhouseTestMixin, APIBaseTest, ABC):
    """Abstract base class for testing web analytics pre-aggregated queries"""

    STANDARD_EVENT_PROPERTIES = {
        "$host": "example.com",
        "$device_type": "Desktop",
        "$browser": "Chrome",
        "$os": "Windows",
        "$viewport_width": 1920,
        "$viewport_height": 1080,
    }

    # Columns that need to be materialized for web analytics pre-aggregated queries
    MATERIALIZED_COLUMNS = [
        "$host",
        "$device_type",
        "$browser",
        "$os",
        "$viewport_width",
        "$viewport_height",
        "$geoip_country_code",
        "$geoip_city_name",
        "$geoip_subdivision_1_code",
        "$pathname",
    ]

    def setUp(self):
        super().setUp()
        self._materialize_required_columns()
        self._setup_test_data()

    def _materialize_required_columns(self):
        """Materialize all columns required for web analytics queries"""
        for column in self.MATERIALIZED_COLUMNS:
            materialize("events", column)

    def _generate_random_distinct_id(self, prefix: str = "user") -> str:
        """Generate a random distinct_id to avoid conflicts between tests"""
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    def _create_test_person(self, distinct_id: str | None = None) -> str:
        """Create a test person and return the distinct_id"""
        if distinct_id is None:
            distinct_id = self._generate_random_distinct_id()
        _create_person(distinct_ids=[distinct_id], team_id=self.team.pk)
        return distinct_id

    def _create_session_event(
        self,
        distinct_id: str,
        session_id: str,
        timestamp: str,
        url: str = "https://example.com/page",
        event: str = "$pageview",
        extra_properties: Optional[dict] = None,
    ) -> None:
        """Create a single session event with standard properties"""
        properties = {
            "$session_id": session_id,
            "$current_url": url,
            "$pathname": url.split("example.com")[-1] if "example.com" in url else "/",
            **self.STANDARD_EVENT_PROPERTIES,
            **(extra_properties or {}),
        }

        _create_event(distinct_id=distinct_id, event=event, team=self.team, timestamp=timestamp, properties=properties)

    def _create_session_with_events(
        self, distinct_id: str, session_id: str, events: list[tuple[str, str]], extra_properties: Optional[dict] = None
    ) -> None:
        for timestamp, url in events:
            with freeze_time(timestamp):
                self._create_session_event(distinct_id, session_id, timestamp, url, extra_properties=extra_properties)

    @abstractmethod
    def _setup_test_data(self):
        """Abstract method to set up test-specific data"""
        pass

    @abstractmethod
    def _get_expected_metrics(self) -> dict:
        """Abstract method to return expected metrics for validation"""
        pass

    def _execute_metrics_query(self, base_sql: str) -> tuple:
        """Execute a metrics query that aggregates pre-aggregated data"""
        metrics_sql = f"""
        WITH session_data AS (
            {base_sql}
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

        results = sync_execute(metrics_sql)
        assert len(results) == 1, "Expected exactly 1 metrics result"
        return results[0]

    def _validate_metrics(self, actual_metrics: tuple, expected_metrics: dict):
        """Validate actual metrics against expected values"""
        unique_persons, total_pageviews, unique_sessions, avg_duration, bounce_sessions, bounce_rate = actual_metrics

        assert unique_persons == expected_metrics["unique_persons"]
        assert total_pageviews == expected_metrics["total_pageviews"]
        assert unique_sessions == expected_metrics["unique_sessions"]
        assert bounce_sessions == expected_metrics["bounce_sessions"]
        assert abs(bounce_rate - expected_metrics["bounce_rate"]) < 0.01
        assert abs(avg_duration - expected_metrics["avg_session_duration"]) < 1.0

    def _get_expected_metrics(self) -> dict:
        """Return expected metrics for the test scenarios"""
        return {
            "unique_persons": 5,
            "total_pageviews": 11,  # 3+1+4+1+2 = 11
            "unique_sessions": 5,
            "bounce_sessions": 2,  # Sessions 2 and 4
            "bounce_rate": 2 / 5,  # 0.4 (40%)
            "avg_session_duration": (600 + 0 + 900 + 0 + 120) / 5,  # 324.0 seconds
        }
