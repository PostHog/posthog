from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch


class TestBillingMCPAPI(APIBaseTest):
    @patch("ee.api.billing_mcp.BillingManager")
    @patch("ee.api.billing_mcp.get_cached_instance_license")
    def test_billing_summary_proxies_to_billing_manager(self, mock_get_license, mock_billing_manager):
        mock_get_license.return_value = MagicMock()
        mock_instance = MagicMock()
        mock_instance.get_mcp_billing_summary.return_value = {"plan": "scale", "subscribed": True}
        mock_billing_manager.return_value = mock_instance

        response = self.client.get(f"/api/environments/{self.team.id}/billing_mcp/billing-summary/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"plan": "scale", "subscribed": True})
        mock_instance.get_mcp_billing_summary.assert_called_once_with(self.organization)
