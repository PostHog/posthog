from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.dashboards.backend.widget_query_throttle import get_dashboard_widget_query_throttle_error


class TestDashboardWidgetQueryThrottle(BaseTest):
    def test_get_dashboard_widget_query_throttle_error_when_burst_blocks(self) -> None:
        request = MagicMock()
        view = MagicMock()
        view.team_id = self.team.id

        with patch(
            "products.dashboards.backend.widget_query_throttle.is_rate_limit_enabled",
            return_value=True,
        ):
            with patch(
                "products.dashboards.backend.widget_query_throttle.DashboardWidgetQueryBurstRateThrottle.allow_request",
                return_value=False,
            ):
                with patch(
                    "products.dashboards.backend.widget_query_throttle.DashboardWidgetQueryBurstRateThrottle.wait",
                    return_value=12,
                ):
                    with patch(
                        "products.dashboards.backend.widget_query_throttle.DashboardWidgetQuerySustainedRateThrottle.allow_request",
                        return_value=True,
                    ):
                        error = get_dashboard_widget_query_throttle_error(request, view)

        self.assertEqual(error, "Rate limit exceeded. Expected available in 12 seconds.")

    def test_get_dashboard_widget_query_throttle_error_returns_none_when_allowed(self) -> None:
        request = MagicMock()
        view = MagicMock()
        view.team_id = self.team.id

        with patch(
            "products.dashboards.backend.widget_query_throttle.is_rate_limit_enabled",
            return_value=True,
        ):
            with patch(
                "products.dashboards.backend.widget_query_throttle.DashboardWidgetQueryBurstRateThrottle.allow_request",
                return_value=True,
            ):
                with patch(
                    "products.dashboards.backend.widget_query_throttle.DashboardWidgetQuerySustainedRateThrottle.allow_request",
                    return_value=True,
                ):
                    error = get_dashboard_widget_query_throttle_error(request, view)

        self.assertIsNone(error)
