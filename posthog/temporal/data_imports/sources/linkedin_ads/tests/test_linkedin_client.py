import json

import pytest
from unittest import mock

from posthog.temporal.data_imports.sources.linkedin_ads.client import LinkedinAdsClient, LinkedinAdsPivot


class TestLinkedinAdsClient:
    """Test suite for LinkedinAdsClient."""

    def setup_method(self):
        """Set up test fixtures."""
        self.access_token = "test_access_token"
        self.account_id = "12345"

    def test_init_with_empty_token_raises_error(self):
        """Test client initialization with empty token raises ValueError."""
        with pytest.raises(ValueError, match="Access token required"):
            LinkedinAdsClient("")

    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_accounts_success(self, mock_restli_client):
        """Test successful accounts retrieval."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.elements = [{"id": "123", "name": "Test Account"}]

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)
        result = client.get_accounts()

        assert result == [{"id": "123", "name": "Test Account"}]
        mock_client_instance.finder.assert_called_once()

    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_accounts_api_error(self, mock_restli_client):
        """Test accounts retrieval with API error."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 401
        mock_response.response.text = "Unauthorized"

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)

        with pytest.raises(Exception, match="LinkedIn API error \\(401\\): Unauthorized"):
            client.get_accounts()

    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_campaigns_pagination(self, mock_restli_client):
        """Test successful campaigns retrieval with pagination."""
        # First page response
        mock_response1 = mock.MagicMock()
        mock_response1.status_code = 200
        mock_response1.elements = [{"id": "camp1", "name": "Campaign 1"}]
        mock_response1.response.text = json.dumps({"metadata": {"nextPageToken": "token123"}})

        # Second page response
        mock_response2 = mock.MagicMock()
        mock_response2.status_code = 200
        mock_response2.elements = [{"id": "camp2", "name": "Campaign 2"}]
        mock_response2.response.text = json.dumps({"metadata": {}})

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.side_effect = [mock_response1, mock_response2]

        client = LinkedinAdsClient(self.access_token)
        pages = list(client.get_campaigns(self.account_id))

        assert len(pages) == 2
        assert pages[0] == [{"id": "camp1", "name": "Campaign 1"}]
        assert pages[1] == [{"id": "camp2", "name": "Campaign 2"}]
        assert mock_client_instance.finder.call_count == 2

    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_analytics_success(self, mock_restli_client):
        """Test successful analytics retrieval."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.elements = [
            {
                "impressions": 1000,
                "clicks": 50,
                "costInUsd": 25.50,
                "dateRange": {"start": {"year": 2024, "month": 1, "day": 1}},
            }
        ]

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)
        result = client.get_analytics(
            account_id=self.account_id, pivot=LinkedinAdsPivot.CAMPAIGN, date_start="2024-01-01", date_end="2024-01-31"
        )

        assert len(result) == 1
        assert result[0]["impressions"] == 1000
        assert result[0]["clicks"] == 50
        assert result[0]["costInUsd"] == 25.50

    def test_format_date_range(self):
        """Test date range formatting for LinkedIn API."""
        client = LinkedinAdsClient(self.access_token)
        result = client._format_date_range("2024-01-15", "2024-02-20")

        expected = {"start": {"year": 2024, "month": 1, "day": 15}, "end": {"year": 2024, "month": 2, "day": 20}}
        assert result == expected
