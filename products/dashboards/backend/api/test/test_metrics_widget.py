from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded

from products.dashboards.backend.widgets.errors import WidgetQueryError
from products.dashboards.backend.widgets.metrics import _run_with_capacity_retries


class TestMetricsWidgetCapacityRetries(SimpleTestCase):
    @parameterized.expand([("a slot frees up", 2, True), ("the dashboard stays full", 99, False)])
    @patch("products.dashboards.backend.widgets.metrics.time.sleep")
    def test_retries_a_run_that_misses_a_dashboard_query_slot(
        self, _name: str, failures: int, succeeds: bool, _sleep: MagicMock
    ) -> None:
        attempts = {"count": 0}

        def run() -> str:
            attempts["count"] += 1
            if attempts["count"] <= failures:
                raise ConcurrencyLimitExceeded("full")
            return "result"

        if succeeds:
            self.assertEqual(_run_with_capacity_retries(run), "result")
        else:
            with self.assertRaises(WidgetQueryError):
                _run_with_capacity_retries(run)
