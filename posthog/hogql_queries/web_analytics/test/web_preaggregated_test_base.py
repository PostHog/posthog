import uuid
from abc import ABC, abstractmethod
from typing import Optional
from freezegun import freeze_time
from urllib.parse import urlparse

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    cleanup_materialized_columns,
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

    def _create_session_event(
        self,
        distinct_id: str,
        session_id: str,
        timestamp: str,
        url: str = "https://example.com/page",
        event: str = "$pageview",
        extra_properties: Optional[dict] = None,
    ) -> None:
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname or ""
        properties = {
            "$session_id": session_id,
            "$current_url": url,
            "$pathname": (url.split(hostname)[-1] if hostname and hostname.endswith(".example.com") else "/"),
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

    def _sort_results(self, results, key=lambda x: str(x[0])):
        return sorted(results, key=key)
