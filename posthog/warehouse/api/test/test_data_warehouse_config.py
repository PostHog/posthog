from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models.team.team_data_warehouse_config import TeamDataWarehouseConfig


class DataWarehouseConfigViewSetTest(APIBaseTest):
    def test_get_data_warehouse_config(self):
        """Test getting the data warehouse config."""
        response = self.client.get(f"/api/environments/{self.team.id}/data_warehouse_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("revenue_analytics_package_view_enabled_at", response.data)

    @patch("posthog.warehouse.api.data_warehouse_config.create_revenue_analytics_managed_views")
    def test_toggle_revenue_analytics_enable(self, mock_create_views):
        """Test enabling revenue analytics creates managed views."""
        response = self.client.post(
            f"/api/environments/{self.team.id}/data_warehouse_config/toggle_revenue_analytics/", {"enabled": True}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check that the create method was called
        mock_create_views.assert_called_once_with(self.team)

        # Check that the config was updated
        config = TeamDataWarehouseConfig.objects.get(team=self.team)
        self.assertIsNotNone(config.revenue_analytics_package_view_enabled_at)

    @patch("posthog.warehouse.api.data_warehouse_config.create_revenue_analytics_managed_views")
    @patch("posthog.warehouse.api.data_warehouse_config.delete_revenue_analytics_managed_views")
    def test_toggle_revenue_analytics_disable(self, mock_delete_views, mock_create_views):
        """Test disabling revenue analytics removes managed views."""
        # First enable it
        self.client.post(
            f"/api/environments/{self.team.id}/data_warehouse_config/toggle_revenue_analytics/", {"enabled": True}
        )

        # Then disable it
        response = self.client.post(
            f"/api/environments/{self.team.id}/data_warehouse_config/toggle_revenue_analytics/", {"enabled": False}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check that the delete method was called
        mock_delete_views.assert_called_once_with(self.team)

        # Check that the config was updated
        config = TeamDataWarehouseConfig.objects.get(team=self.team)
        self.assertIsNone(config.revenue_analytics_package_view_enabled_at)

    @patch("posthog.warehouse.api.data_warehouse_config.create_revenue_analytics_managed_views")
    @patch("posthog.warehouse.api.data_warehouse_config.delete_revenue_analytics_managed_views")
    def test_toggle_revenue_analytics_auto_toggle(self, mock_delete_views, mock_create_views):
        """Test automatic toggling without parameters."""
        # Start disabled, toggle should enable
        response = self.client.post(f"/api/environments/{self.team.id}/data_warehouse_config/toggle_revenue_analytics/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check that create method was called
        mock_create_views.assert_called_once_with(self.team)

        # Toggle again should disable
        response = self.client.post(f"/api/environments/{self.team.id}/data_warehouse_config/toggle_revenue_analytics/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check that delete method was called
        mock_delete_views.assert_called_once_with(self.team)
