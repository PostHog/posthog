"""Tests for LinkedIn Ads client functionality."""

import pytest
from unittest.mock import Mock, patch

from .client import LinkedinAdsClient
from .exceptions import LinkedinAdsAuthError, LinkedinAdsRateLimitError


class TestLinkedInAdsClient:
    """Test LinkedIn Ads client functionality."""

    @patch("requests.Session.get")
    def test_get_accounts_success(self, mock_get):
        """Test successful account fetching."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "elements": [
                {
                    "id": "123456789",
                    "name": "Test Account",
                    "status": "ACTIVE",
                    "type": "BUSINESS",
                    "currency": "USD",
                    "version": {"versionTag": "1"},
                }
            ]
        }
        mock_get.return_value = mock_response

        client = LinkedinAdsClient("test_token")
        result = client.get_accounts()

        assert len(result) == 1
        assert result[0]["id"] == "123456789"
        assert result[0]["name"] == "Test Account"

    @patch("requests.Session.get")
    def test_get_campaigns_success(self, mock_get):
        """Test successful campaign fetching."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "elements": [
                {
                    "id": "987654321",
                    "name": "Test Campaign",
                    "account": "urn:li:sponsoredAccount:123456789",
                    "campaignGroup": "urn:li:sponsoredCampaignGroup:555",
                    "status": "ACTIVE",
                    "type": "SPONSORED_CONTENT",
                    "changeAuditStamps": {"created": {"time": 1609459200000}, "lastModified": {"time": 1609459200000}},
                    "runSchedule": {"start": 1609459200000},
                    "dailyBudget": {"amount": "100", "currencyCode": "USD"},
                    "unitCost": {"amount": "1.50", "currencyCode": "USD"},
                    "costType": "CPM",
                    "targetingCriteria": {},
                    "locale": {"country": "US", "language": "en"},
                    "version": {"versionTag": "1"},
                }
            ]
        }
        mock_get.return_value = mock_response

        client = LinkedinAdsClient("test_token")
        result = client.get_campaigns("123456789")

        assert len(result) == 1
        assert result[0]["id"] == "987654321"
        assert result[0]["name"] == "Test Campaign"

    @patch("requests.Session.get")
    def test_get_analytics_success(self, mock_get):
        """Test successful analytics fetching."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "elements": [
                {
                    "pivotValues": ["urn:li:sponsoredCampaign:123"],
                    "dateRange": {
                        "start": {"year": 2023, "month": 1, "day": 1},
                        "end": {"year": 2023, "month": 1, "day": 31},
                    },
                    "impressions": 1000,
                    "clicks": 50,
                    "costInUsd": "150.00",
                    "externalWebsiteConversions": 5,
                    "landingPageClicks": 45,
                    "totalEngagements": 75,
                    "videoViews": 20,
                    "videoCompletions": 10,
                    "oneClickLeads": 2,
                    "follows": 3,
                }
            ]
        }
        mock_get.return_value = mock_response

        client = LinkedinAdsClient("test_token")
        result = client.get_analytics("123456789", "CAMPAIGN", "2023-01-01", "2023-01-31")

        assert len(result) == 1
        assert result[0]["impressions"] == 1000
        assert result[0]["clicks"] == 50

    @patch("requests.Session.get")
    def test_auth_error_handling(self, mock_get):
        """Test authentication error handling."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_get.return_value = mock_response

        client = LinkedinAdsClient("invalid_token")

        with pytest.raises(LinkedinAdsAuthError, match="LinkedIn API authentication failed"):
            client.get_accounts()

    @patch("requests.Session.get")
    def test_rate_limit_error_handling(self, mock_get):
        """Test rate limit error handling."""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.text = "Too Many Requests"
        mock_response.headers = {"Retry-After": "60"}
        mock_get.return_value = mock_response

        client = LinkedinAdsClient("test_token")

        with patch("time.sleep"):  # Skip actual sleep
            with pytest.raises(LinkedinAdsRateLimitError, match="LinkedIn API rate limit exceeded"):
                client.get_accounts()

    @patch("requests.Session.get")
    def test_server_error_with_retry(self, mock_get):
        """Test server error handling with retry."""
        # First call returns 500, second succeeds
        mock_response_500 = Mock()
        mock_response_500.status_code = 500
        mock_response_500.text = "Internal Server Error"

        mock_response_200 = Mock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {"elements": [{"id": "123"}]}

        mock_get.side_effect = [mock_response_500, mock_response_200]

        client = LinkedinAdsClient("test_token")

        with patch("time.sleep"):  # Skip actual sleep
            result = client.get_accounts()

        assert result == [{"id": "123"}]

    def test_client_initialization(self):
        """Test client initialization with access token."""
        client = LinkedinAdsClient("test_token")

        assert client.access_token == "test_token"
        assert client.base_url == "https://api.linkedin.com/rest"
        assert client.request_handler is not None
        assert client.date_handler is not None

    def test_invalid_pivot_validation(self):
        """Test that invalid pivot values are rejected."""
        client = LinkedinAdsClient("test_token")

        with pytest.raises(ValueError, match="Invalid pivot 'INVALID'"):
            client.get_analytics("123", "INVALID", "2023-01-01", "2023-01-31")
