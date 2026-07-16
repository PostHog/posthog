from unittest.mock import MagicMock, patch

from parameterized import parameterized
from prometheus_client import REGISTRY
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.event_usage import EventSource

from products.dashboards.backend.access import (
    DashboardAccessMethod,
    dashboard_access_method,
    record_dashboard_access,
    record_dashboard_cache_outcome,
)


class TestDashboardAccessMetrics:
    @parameterized.expand(
        [
            (False, EventSource.WEB, DashboardAccessMethod.HUMAN),
            (False, EventSource.API, DashboardAccessMethod.API),
            (True, EventSource.WEB, DashboardAccessMethod.EMBEDDED),
        ]
    )
    @patch("products.dashboards.backend.access.get_event_source")
    def test_classifies_dashboard_access(
        self,
        is_embedded: bool,
        event_source: EventSource,
        expected: DashboardAccessMethod,
        mock_get_event_source: MagicMock,
    ) -> None:
        request = Request(APIRequestFactory().get("/"))
        mock_get_event_source.return_value = event_source

        assert dashboard_access_method(request, is_embedded=is_embedded) == expected

    @parameterized.expand([(access_method,) for access_method in DashboardAccessMethod])
    def test_records_dashboard_access(self, access_method: DashboardAccessMethod) -> None:
        labels = {"access_method": access_method.value}
        before = REGISTRY.get_sample_value("posthog_dashboard_access_total", labels) or 0

        record_dashboard_access(access_method)

        assert REGISTRY.get_sample_value("posthog_dashboard_access_total", labels) == before + 1

    @parameterized.expand(
        [
            (DashboardAccessMethod.HUMAN, True, "hit"),
            (DashboardAccessMethod.EMBEDDED, False, "miss"),
            (DashboardAccessMethod.API, True, "hit"),
        ]
    )
    def test_records_dashboard_cache_outcome(
        self,
        access_method: DashboardAccessMethod,
        is_cached: bool,
        expected_result: str,
    ) -> None:
        labels = {"access_method": access_method.value, "result": expected_result}
        before = REGISTRY.get_sample_value("posthog_dashboard_cache_outcome_total", labels) or 0

        record_dashboard_cache_outcome(access_method, is_cached=is_cached)

        assert REGISTRY.get_sample_value("posthog_dashboard_cache_outcome_total", labels) == before + 1
