import pytest
from unittest.mock import Mock, patch

from posthog.models import Team
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig
from posthog.temporal.data_imports.sources.linkedin_ads.client import LinkedinAdsClient
from posthog.temporal.data_imports.sources.linkedin_ads.client.exceptions import (
    LinkedinAdsAuthError,
    LinkedinAdsRateLimitError,
)
from posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads import linkedin_ads_source
from posthog.temporal.data_imports.sources.linkedin_ads.source import LinkedInAdsSource
from posthog.temporal.data_imports.sources.linkedin_ads.utils import _failure_counts, _last_failure_time
from posthog.temporal.data_imports.sources.linkedin_ads.utils.constants import CIRCUIT_BREAKER_THRESHOLD
from posthog.warehouse.types import ExternalDataSourceType, IncrementalFieldType


class TestLinkedInAdsClient:
    """Test LinkedIn Ads client functionality."""

    def test_client_initialization(self):
        """Test client initializes correctly."""
        client = LinkedinAdsClient("test_token")
        assert client.access_token == "test_token"
        assert client.session.headers["Authorization"] == "Bearer test_token"
        assert client.session.headers["LinkedIn-Version"] == "202508"

    def test_client_initialization_empty_token(self):
        """Test client raises error with empty token."""
        with pytest.raises(ValueError, match="Access token is required"):
            LinkedinAdsClient("")

    @patch("requests.Session.get")
    def test_make_request_success(self, mock_get):
        """Test successful API request."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"elements": [{"id": "123"}]}
        mock_get.return_value = mock_response

        client = LinkedinAdsClient("test_token")
        result = client.request_handler.make_request("test_endpoint")

        assert result == {"elements": [{"id": "123"}]}

    @patch("requests.Session.get")
    def test_make_request_auth_error(self, mock_get):
        """Test authentication error handling."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"message": "Invalid token"}
        mock_get.return_value = mock_response

        client = LinkedinAdsClient("test_token")

        with pytest.raises(LinkedinAdsAuthError, match="LinkedIn API authentication failed"):
            client.request_handler.make_request("test_endpoint")

    @patch("requests.Session.get")
    def test_make_request_rate_limit_with_retry(self, mock_get):
        """Test rate limit handling with successful retry."""
        # First call returns 429, second succeeds
        mock_response_429 = Mock()
        mock_response_429.status_code = 429
        mock_response_429.headers = {"Retry-After": "1"}

        mock_response_200 = Mock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {"success": True}

        mock_get.side_effect = [mock_response_429, mock_response_200]

        client = LinkedinAdsClient("test_token")

        with patch("time.sleep"):  # Skip actual sleep
            result = client.request_handler.make_request("test_endpoint")

        assert result == {"success": True}
        assert mock_get.call_count == 2

    @patch("requests.Session.get")
    def test_make_request_rate_limit_max_retries(self, mock_get):
        """Test rate limit error after max retries."""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "60"}
        mock_get.return_value = mock_response

        client = LinkedinAdsClient("test_token")

        with patch("time.sleep"):  # Skip actual sleep
            with pytest.raises(LinkedinAdsRateLimitError, match="LinkedIn API rate limit exceeded"):
                client.request_handler.make_request("test_endpoint")

    @patch("requests.Session.get")
    def test_make_request_server_error_with_retry(self, mock_get):
        """Test server error handling with retry."""
        # First call returns 500, second succeeds
        mock_response_500 = Mock()
        mock_response_500.status_code = 500
        mock_response_500.text = "Internal Server Error"

        mock_response_200 = Mock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {"success": True}

        mock_get.side_effect = [mock_response_500, mock_response_200]

        client = LinkedinAdsClient("test_token")

        with patch("time.sleep"):  # Skip actual sleep
            result = client.request_handler.make_request("test_endpoint")

        assert result == {"success": True}
        assert mock_get.call_count == 2


@pytest.mark.django_db
class TestLinkedInAdsSource:
    """Test LinkedIn Ads source wrapper."""

    def setup_method(self):
        """Set up test fixtures."""
        self.org = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.org)
        self.source = LinkedInAdsSource()

    def test_source_type(self):
        """Test source type is correct."""
        assert self.source.source_type == ExternalDataSourceType.LINKEDINADS

    def test_validate_credentials_missing_account_id(self):
        """Test credential validation with missing account ID."""
        config = LinkedinAdsSourceConfig(account_id="", linkedin_ads_integration_id=123)

        valid, error = self.source.validate_credentials(config, self.team.id)
        assert valid is False
        assert error is not None and "Account ID is required" in error

    def test_validate_credentials_invalid_account_id_format(self):
        """Test credential validation with invalid account ID format."""
        config = LinkedinAdsSourceConfig(account_id="invalid-id", linkedin_ads_integration_id=123)

        valid, error = self.source.validate_credentials(config, self.team.id)
        assert valid is False
        assert error is not None and "Invalid account ID format" in error

    def test_validate_credentials_missing_integration(self):
        """Test credential validation with missing integration."""
        config = LinkedinAdsSourceConfig(
            account_id="123456789",
            linkedin_ads_integration_id=99999999,  # Non-existent integer ID
        )

        valid, error = self.source.validate_credentials(config, self.team.id)
        assert valid is False
        assert error is not None and "LinkedIn Ads integration not found" in error

    def test_validate_credentials_missing_access_token(self):
        """Test credential validation with missing access token."""
        # Create integration without access token (check the model to see what's required)
        integration = Integration.objects.create(
            team=self.team,
            kind="linkedin-ads",
            config={"client_id": "test", "client_secret": "test"},
            # Don't set access_token to test the missing token case
        )

        config = LinkedinAdsSourceConfig(account_id="123456789", linkedin_ads_integration_id=integration.id)

        valid, error = self.source.validate_credentials(config, self.team.id)
        assert valid is False
        assert error is not None and "access token not found" in error


@pytest.mark.django_db
class TestLinkedInAdsIntegration:
    """Integration tests for LinkedIn Ads source with mocked API responses."""

    def setup_method(self):
        """Set up test fixtures."""
        self.org = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.org)
        self.integration = Integration.objects.create(
            team=self.team,
            kind="linkedin-ads",
            config={"client_id": "test", "client_secret": "test"},
        )
        # Clear circuit breaker state before each test
        _failure_counts.clear()
        _last_failure_time.clear()

    def teardown_method(self):
        """Clean up after each test."""
        # Clear circuit breaker state after each test
        _failure_counts.clear()
        _last_failure_time.clear()

    def _mock_access_token(self):
        """Helper method to mock access_token property."""
        return patch.object(
            type(self.integration), "access_token", new_callable=lambda: property(lambda self: "test_access_token")
        )

    @patch("posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads.LinkedinAdsClient")
    def test_get_schemas_success(self, mock_client_class):
        """Test successful schema retrieval."""
        # Mock the client
        mock_client = Mock()
        mock_client.get_accounts.return_value = [{"id": "123456789", "name": "Test Account"}]
        mock_client_class.return_value = mock_client

        source = LinkedInAdsSource()
        config = LinkedinAdsSourceConfig(account_id="123456789", linkedin_ads_integration_id=self.integration.id)

        with self._mock_access_token():
            schemas = source.get_schemas(config, self.team.id)

        assert len(schemas) > 0
        schema_names = [schema.name for schema in schemas]
        assert "accounts" in schema_names
        assert "campaigns" in schema_names
        assert "campaign_stats" in schema_names

    @patch("posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads.LinkedinAdsClient")
    def test_linkedin_ads_source_accounts(self, mock_client_class):
        """Test LinkedIn Ads source for accounts resource."""
        # Mock the client
        mock_client = Mock()
        mock_client.get_accounts.return_value = [
            {
                "id": "123456789",
                "name": "Test Account",
                "status": "ACTIVE",
                "type": "BUSINESS",
                "currency": "USD",
                "version": {"versionTag": "1.0"},
            }
        ]
        mock_client_class.return_value = mock_client

        config = LinkedinAdsSourceConfig(account_id="123456789", linkedin_ads_integration_id=self.integration.id)

        with self._mock_access_token():
            response = linkedin_ads_source(
                config=config, resource_name="accounts", team_id=self.team.id, should_use_incremental_field=False
            )

        assert response.name == "accounts"
        items = list(response.items)
        assert len(items) == 1
        assert items[0]["id"] == "123456789"
        assert items[0]["name"] == "Test Account"
        assert response.primary_keys == ["id"]

    @patch("posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads.LinkedinAdsClient")
    def test_linkedin_ads_source_campaigns(self, mock_client_class):
        """Test LinkedIn Ads source for campaigns resource."""
        # Mock the client
        mock_client = Mock()
        mock_client.get_campaigns.return_value = [
            {
                "id": "987654321",
                "name": "Test Campaign",
                "account": "urn:li:sponsoredAccount:123456789",
                "status": "ACTIVE",
                "changeAuditStamps": {"created": {"time": 1609459200000}, "lastModified": {"time": 1609459200000}},
            }
        ]
        mock_client_class.return_value = mock_client

        config = LinkedinAdsSourceConfig(account_id="123456789", linkedin_ads_integration_id=self.integration.id)

        with self._mock_access_token():
            response = linkedin_ads_source(
                config=config, resource_name="campaigns", team_id=self.team.id, should_use_incremental_field=False
            )

        assert response.name == "campaigns"
        items = list(response.items)
        assert len(items) == 1
        assert items[0]["id"] == "987654321"
        assert items[0]["name"] == "Test Campaign"
        assert "created_time" in items[0]
        assert "last_modified_time" in items[0]

    @patch("posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads.LinkedinAdsClient")
    def test_linkedin_ads_source_campaign_stats(self, mock_client_class):
        """Test LinkedIn Ads source for campaign analytics."""
        # Mock the client
        mock_client = Mock()
        mock_client.get_analytics.return_value = [
            {
                "pivotValues": ["urn:li:sponsoredCampaign:987654321"],
                "dateRange": {
                    "start": {"year": 2025, "month": 8, "day": 1},
                    "end": {"year": 2025, "month": 8, "day": 1},
                },
                "impressions": 1000,
                "clicks": 50,
                "costInUsd": "25.50",
            }
        ]
        mock_client_class.return_value = mock_client

        config = LinkedinAdsSourceConfig(account_id="123456789", linkedin_ads_integration_id=self.integration.id)

        with self._mock_access_token():
            response = linkedin_ads_source(
                config=config,
                resource_name="campaign_stats",
                team_id=self.team.id,
                should_use_incremental_field=True,
                incremental_field="dateRange.start",
                incremental_field_type=IncrementalFieldType.Date,
                date_start="2025-08-01",
            )

        assert response.name == "campaign_stats"
        items = list(response.items)
        assert len(items) == 1
        item = items[0]
        assert item["impressions"] == 1000
        assert item["clicks"] == 50
        assert item["cost_in_usd"] == 25.50  # Converted to float
        assert item["campaign_id"] == 987654321  # Extracted from URN
        assert "date_range_start" in item
        assert "date_range_end" in item

    @patch("posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads.LinkedinAdsClient")
    def test_linkedin_ads_source_circuit_breaker_integration(self, mock_client_class):
        """Test circuit breaker integration in the full source flow."""
        # Mock client to always fail
        mock_client = Mock()
        mock_client.get_accounts.side_effect = Exception("API Error")
        mock_client_class.return_value = mock_client

        config = LinkedinAdsSourceConfig(account_id="123456789", linkedin_ads_integration_id=self.integration.id)

        # Trigger failures up to threshold
        with self._mock_access_token():
            for _i in range(CIRCUIT_BREAKER_THRESHOLD):
                with pytest.raises(Exception):
                    linkedin_ads_source(config=config, resource_name="accounts", team_id=self.team.id)

        # Next call should fail due to circuit breaker
        with self._mock_access_token():
            with pytest.raises(ValueError, match="Circuit breaker open"):
                linkedin_ads_source(config=config, resource_name="accounts", team_id=self.team.id)

    def test_validate_credentials_integration_success(self):
        """Test successful credential validation with real flow."""
        with patch(
            "posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads.LinkedinAdsClient"
        ) as mock_client_class:
            mock_client = Mock()
            mock_client.get_accounts.return_value = [{"id": "123456789", "name": "Test Account"}]
            mock_client_class.return_value = mock_client

            source = LinkedInAdsSource()
            config = LinkedinAdsSourceConfig(account_id="123456789", linkedin_ads_integration_id=self.integration.id)

            with self._mock_access_token():
                valid, error = source.validate_credentials(config, self.team.id)

            assert valid is True
            assert error is None
