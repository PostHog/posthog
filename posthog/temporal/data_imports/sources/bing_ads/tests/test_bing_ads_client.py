from unittest import mock

from posthog.temporal.data_imports.sources.bing_ads.client import BingAdsClient


class TestBingAdsClient:
    """Test suite for BingAdsClient."""

    def setup_method(self):
        """Set up test fixtures."""
        self.access_token = "test_access_token"
        self.refresh_token = "test_refresh_token"
        self.developer_token = "test_developer_token"
        self.account_id = 12345
        self.customer_id = 67890

    @mock.patch("posthog.temporal.data_imports.sources.bing_ads.client.ServiceClient")
    def test_get_customer_id_success(self, mock_service_client):
        """Test successful customer ID retrieval."""
        mock_user = mock.MagicMock()
        mock_user.CustomerId = self.customer_id

        mock_response = mock.MagicMock()
        mock_response.User = mock_user

        mock_client_instance = mock_service_client.return_value
        mock_client_instance.GetUser.return_value = mock_response

        client = BingAdsClient(self.access_token, self.refresh_token, self.developer_token)
        result = client.get_customer_id()

        assert result == self.customer_id
        assert client._customer_id == self.customer_id
        mock_client_instance.GetUser.assert_called_once_with(UserId=None)

    @mock.patch("posthog.temporal.data_imports.sources.bing_ads.client.ServiceClient")
    def test_get_campaigns_success(self, mock_service_client):
        """Test successful campaigns retrieval."""
        mock_campaign = mock.MagicMock()
        mock_campaign.Id = 123
        mock_campaign.Name = "Test Campaign"
        mock_campaign.Status = "Active"
        mock_campaign.CampaignType = "Search"
        mock_campaign.BudgetType = "DailyBudgetStandard"
        mock_campaign.DailyBudget = 100
        mock_campaign.AudienceAdsBidAdjustment = 0
        mock_campaign.TimeZone = "PacificTimeUSCanadaTijuana"

        mock_languages = mock.MagicMock()
        mock_languages.string = ["English"]
        mock_campaign.Languages = mock_languages

        mock_campaigns = mock.MagicMock()
        mock_campaigns.Campaign = [mock_campaign]

        mock_client_instance = mock_service_client.return_value
        mock_client_instance.GetCampaignsByAccountId.return_value = mock_campaigns

        client = BingAdsClient(self.access_token, self.refresh_token, self.developer_token)
        result = list(client.get_campaigns(self.account_id, self.customer_id))

        assert len(result) == 1
        assert len(result[0]) == 1
        campaign_data = result[0][0]
        assert campaign_data["Id"] == 123
        assert campaign_data["Name"] == "Test Campaign"
        assert campaign_data["Status"] == "Active"
        assert campaign_data["Languages"] == ["English"]
