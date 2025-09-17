import uuid
from abc import ABC, abstractmethod

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    cleanup_materialized_columns,
    flush_persons_and_events,
)

from posthog.models.utils import uuid7

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

    # Columns that need to be materialized for web analytics pre-aggregated queries to work
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
        # EU-specific customer fields
        "metadata.loggedIn",
        "metadata.backend",
    ]

    def setUp(self):
        super().setUp()
        self._materialize_required_columns()
        self._setup_test_data()

    def tearDown(self):
        cleanup_materialized_columns()

    @abstractmethod
    def _setup_test_data(self):
        pass

    def _materialize_required_columns(self):
        for column in self.MATERIALIZED_COLUMNS:
            materialize("events", column)

    def _generate_random_distinct_id(self, prefix: str = "user") -> str:
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    def _create_test_person(self, distinct_id: str | None = None) -> str:
        if distinct_id is None:
            distinct_id = self._generate_random_distinct_id()
        _create_person(distinct_ids=[distinct_id], team_id=self.team.pk)
        return distinct_id

    def _sort_results(self, results, key=lambda x: str(x[0])):
        return sorted(results, key=key)

    def _add_extra_timezone_boundary_events(self, team):
        """Add events that extend well into Jan 16 to cover timezone boundaries"""
        additional_events = [
            ("2024-01-16T02:00:00Z", "Chrome", "boundary_user_1", "jan16_02h"),
            ("2024-01-16T04:00:00Z", "Safari", "boundary_user_2", "jan16_04h"),
            ("2024-01-16T06:00:00Z", "Firefox", "boundary_user_3", "jan16_06h"),
            ("2024-01-16T08:00:00Z", "Edge", "boundary_user_4", "jan16_08h"),
            ("2024-01-16T10:00:00Z", "Chrome", "boundary_user_5", "jan16_10h"),
            ("2024-01-16T12:00:00Z", "Safari", "boundary_user_6", "jan16_12h"),
            ("2024-01-16T14:00:00Z", "Firefox", "boundary_user_7", "jan16_14h"),
            ("2024-01-16T16:00:00Z", "Edge", "boundary_user_8", "jan16_16h"),
        ]

        sessions = [str(uuid7("2024-01-16")) for _ in range(len(additional_events))]

        for i in range(len(additional_events)):
            _create_person(team_id=team.pk, distinct_ids=[f"boundary_user_{i+1}"])

        for i, (timestamp, browser, user_id, label) in enumerate(additional_events):
            _create_event(
                team=team,
                event="$pageview",
                distinct_id=user_id,
                timestamp=timestamp,
                properties={
                    "$session_id": sessions[i],
                    "$current_url": f"https://example.com/{label}",
                    "$pathname": f"/{label}",
                    "$device_type": "Desktop",
                    "$browser": browser,
                    "$host": "example.com",
                    "test_label": label,
                },
            )

        flush_persons_and_events()

    def _setup_cross_timezone_test_data(self, team):
        """Create events across multiple days with timezone-aware timestamps"""
        events = [
            # Day 1: Jan 14 - Events that will cross timezone boundaries
            ("2024-01-14T06:00:00Z", "Chrome", "user_1", "early_utc"),
            ("2024-01-14T12:00:00Z", "Safari", "user_2", "midday_utc"),
            ("2024-01-14T18:00:00Z", "Firefox", "user_3", "evening_utc"),
            ("2024-01-14T23:30:00Z", "Edge", "user_4", "late_utc"),
            # Day 2: Jan 15 - Main test day
            ("2024-01-15T03:00:00Z", "Chrome", "user_5", "early_jan15"),
            ("2024-01-15T09:00:00Z", "Safari", "user_6", "morning_jan15"),
            ("2024-01-15T15:00:00Z", "Firefox", "user_7", "afternoon_jan15"),
            ("2024-01-15T21:00:00Z", "Edge", "user_8", "night_jan15"),
            # Day 3: Jan 16 - Events for boundary testing
            ("2024-01-16T02:00:00Z", "Chrome", "user_9", "jan16_early"),
            ("2024-01-16T14:00:00Z", "Safari", "user_10", "jan16_afternoon"),
        ]

        sessions = [str(uuid7("2024-01-15")) for _ in range(len(events))]

        for i in range(len(events)):
            _create_person(team_id=team.pk, distinct_ids=[f"user_{i+1}"])

        for i, (timestamp, browser, user_id, label) in enumerate(events):
            _create_event(
                team=team,
                event="$pageview",
                distinct_id=user_id,
                timestamp=timestamp,
                properties={
                    "$session_id": sessions[i],
                    "$current_url": f"https://example.com/{label}",
                    "$pathname": f"/{label}",
                    "$device_type": "Desktop",
                    "$browser": browser,
                    "$host": "example.com",
                    "test_label": label,
                },
            )

        flush_persons_and_events()
