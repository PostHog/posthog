import pytest
from unittest.mock import Mock, patch
import datetime as dt

from posthog.models import Team
from posthog.models.organization import Organization
from posthog.models.integration import Integration
from posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads import (
    validate_account_id,
    validate_date_format,
    validate_pivot_value,
    extract_linkedin_id_from_urn,
    check_circuit_breaker,
    record_failure,
    record_success,
    LinkedinAdsClient,
    LinkedinAdsError,
    LinkedinAdsAuthError,
    LinkedinAdsRateLimitError,
    _failure_counts,
    _last_failure_time,
    CIRCUIT_BREAKER_THRESHOLD,
)
from posthog.temporal.data_imports.sources.linkedin_ads.source import LinkedinAdsSource
from posthog.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig


class TestLinkedInAdsValidators:
    """Test validation helper functions."""

    def test_validate_account_id_valid(self):
        """Test account ID validation with valid IDs."""
        assert validate_account_id("123456789") is True
        assert validate_account_id("12345678") is True
        assert validate_account_id("123456789012345") is True

    def test_validate_account_id_invalid(self):
        """Test account ID validation with invalid IDs."""
        assert validate_account_id("") is False
        assert validate_account_id("12345") is False  # Too short
        assert validate_account_id("1234567890123456") is False  # Too long
        assert validate_account_id("abc123456") is False  # Non-numeric
        assert validate_account_id("123-456-789") is False  # Contains dashes
        assert validate_account_id("  123456789  ") is True  # Whitespace trimmed

    def test_validate_date_format_valid(self):
        """Test date format validation with valid dates."""
        assert validate_date_format("2024-01-01") is True
        assert validate_date_format("2024-12-31") is True
        assert validate_date_format("2025-08-15") is True

    def test_validate_date_format_invalid(self):
        """Test date format validation with invalid dates."""
        assert validate_date_format("") is False
        assert validate_date_format("2024-1-1") is False  # Wrong format
        assert validate_date_format("01-01-2024") is False  # Wrong format
        assert validate_date_format("2024/01/01") is False  # Wrong separator
        assert validate_date_format("2024-13-01") is False  # Invalid month
        assert validate_date_format("2024-01-32") is False  # Invalid day
        assert validate_date_format("not-a-date") is False

    def test_validate_pivot_value_valid(self):
        """Test pivot value validation with valid values."""
        assert validate_pivot_value("CAMPAIGN") is True
        assert validate_pivot_value("CAMPAIGN_GROUP") is True
        assert validate_pivot_value("CREATIVE") is True
        assert validate_pivot_value("ACCOUNT") is True

    def test_validate_pivot_value_invalid(self):
        """Test pivot value validation with invalid values."""
        assert validate_pivot_value("") is False
        assert validate_pivot_value("INVALID") is False
        assert validate_pivot_value("campaign") is False  # Case sensitive
        assert validate_pivot_value("CAMPAIGN_GROUPS") is False  # Wrong spelling

    def test_extract_linkedin_id_from_urn(self):
        """Test LinkedIn URN ID extraction."""
        assert extract_linkedin_id_from_urn("urn:li:sponsoredCampaign:185129613") == "185129613"
        assert extract_linkedin_id_from_urn("urn:li:sponsoredAccount:123456789") == "123456789"
        assert extract_linkedin_id_from_urn("urn:li:sponsoredCreative:987654321") == "987654321"
        assert extract_linkedin_id_from_urn("") == ""
        assert extract_linkedin_id_from_urn("invalid-urn") == "invalid-urn"


class TestLinkedInAdsCircuitBreaker:
    """Test circuit breaker functionality."""

    def setup_method(self):
        """Reset circuit breaker state before each test."""
        _failure_counts.clear()
        _last_failure_time.clear()

    def test_circuit_breaker_initial_state(self):
        """Test circuit breaker starts in closed state."""
        assert check_circuit_breaker("123456789") is False

    def test_circuit_breaker_opens_after_failures(self):
        """Test circuit breaker opens after threshold failures."""
        account_id = "123456789"
        
        # Record failures up to threshold
        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            record_failure(account_id)
        
        # Circuit should now be open
        assert check_circuit_breaker(account_id) is True

    def test_circuit_breaker_resets_on_success(self):
        """Test circuit breaker resets on success."""
        account_id = "123456789"
        
        # Record some failures
        for _ in range(3):
            record_failure(account_id)
        
        # Record success
        record_success(account_id)
        
        # Circuit should be closed
        assert check_circuit_breaker(account_id) is False

    @patch('time.time')
    def test_circuit_breaker_timeout_reset(self, mock_time):
        """Test circuit breaker resets after timeout."""
        account_id = "123456789"
        
        # Start at time 0
        mock_time.return_value = 0
        
        # Record failures to open circuit
        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            record_failure(account_id)
        
        assert check_circuit_breaker(account_id) is True
        
        # Advance time past timeout
        mock_time.return_value = 400  # Beyond 300 second timeout
        
        # Circuit should be closed now
        assert check_circuit_breaker(account_id) is False


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

    @patch('requests.Session.get')
    def test_make_request_success(self, mock_get):
        """Test successful API request."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"elements": [{"id": "123"}]}
        mock_get.return_value = mock_response

        client = LinkedinAdsClient("test_token")
        result = client._make_request("test_endpoint")
        
        assert result == {"elements": [{"id": "123"}]}

    @patch('requests.Session.get')
    def test_make_request_auth_error(self, mock_get):
        """Test authentication error handling."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"message": "Invalid token"}
        mock_get.return_value = mock_response

        client = LinkedinAdsClient("test_token")
        
        with pytest.raises(LinkedinAdsAuthError, match="LinkedIn API authentication failed"):
            client._make_request("test_endpoint")

    @patch('requests.Session.get')
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
        
        with patch('time.sleep'):  # Skip actual sleep
            result = client._make_request("test_endpoint")
        
        assert result == {"success": True}
        assert mock_get.call_count == 2

    @patch('requests.Session.get')
    def test_make_request_rate_limit_max_retries(self, mock_get):
        """Test rate limit error after max retries."""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "60"}
        mock_get.return_value = mock_response

        client = LinkedinAdsClient("test_token")
        
        with patch('time.sleep'):  # Skip actual sleep
            with pytest.raises(LinkedinAdsRateLimitError, match="LinkedIn API rate limit exceeded"):
                client._make_request("test_endpoint")

    @patch('requests.Session.get')
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
        
        with patch('time.sleep'):  # Skip actual sleep
            result = client._make_request("test_endpoint")
        
        assert result == {"success": True}
        assert mock_get.call_count == 2


@pytest.mark.django_db
class TestLinkedInAdsSource:
    """Test LinkedIn Ads source wrapper."""

    def setup_method(self):
        """Set up test fixtures."""
        self.org = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.org)
        self.source = LinkedinAdsSource()

    def test_source_type(self):
        """Test source type is correct."""
        from posthog.warehouse.types import ExternalDataSourceType
        assert self.source.source_type == ExternalDataSourceType.LINKEDINADS

    def test_validate_credentials_missing_account_id(self):
        """Test credential validation with missing account ID."""
        config = LinkedinAdsSourceConfig(
            account_id="",
            linkedin_ads_integration_id="123"
        )
        
        valid, error = self.source.validate_credentials(config, self.team.id)
        assert valid is False
        assert "Account ID is required" in error

    def test_validate_credentials_invalid_account_id_format(self):
        """Test credential validation with invalid account ID format."""
        config = LinkedinAdsSourceConfig(
            account_id="invalid-id",
            linkedin_ads_integration_id="123"
        )
        
        valid, error = self.source.validate_credentials(config, self.team.id)
        assert valid is False
        assert "Invalid account ID format" in error

    def test_validate_credentials_missing_integration(self):
        """Test credential validation with missing integration."""
        config = LinkedinAdsSourceConfig(
            account_id="123456789",
            linkedin_ads_integration_id="99999999"  # Non-existent integer ID
        )
        
        valid, error = self.source.validate_credentials(config, self.team.id)
        assert valid is False
        assert "LinkedIn Ads integration not found" in error

    def test_validate_credentials_missing_access_token(self):
        """Test credential validation with missing access token."""
        # Create integration without access token (check the model to see what's required)
        integration = Integration.objects.create(
            team=self.team,
            kind="linkedin-ads",
            config={"client_id": "test", "client_secret": "test"},
            # Don't set access_token to test the missing token case
        )
        
        config = LinkedinAdsSourceConfig(
            account_id="123456789",
            linkedin_ads_integration_id=str(integration.id)
        )
        
        valid, error = self.source.validate_credentials(config, self.team.id)
        assert valid is False
        assert "access token not found" in error


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
        # Mock access token via property
        with patch.object(type(self.integration), 'access_token', new_callable=lambda: property(lambda self: "test_access_token")):
            pass

    @patch('posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads.LinkedinAdsClient')
    def test_get_schemas_success(self, mock_client_class):
        """Test successful schema retrieval."""
        from posthog.temporal.data_imports.sources.linkedin_ads.source import LinkedinAdsSource
        from posthog.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig

        # Mock the client
        mock_client = Mock()
        mock_client.get_accounts.return_value = [
            {"id": "123456789", "name": "Test Account"}
        ]
        mock_client_class.return_value = mock_client

        source = LinkedinAdsSource()
        config = LinkedinAdsSourceConfig(
            account_id="123456789",
            linkedin_ads_integration_id=str(self.integration.id)
        )

        with patch.object(type(self.integration), 'access_token', new_callable=lambda: property(lambda self: "test_access_token")):
            schemas = source.get_schemas(config, self.team.id)

        assert len(schemas) > 0
        schema_names = [schema.name for schema in schemas]
        assert "accounts" in schema_names
        assert "campaigns" in schema_names
        assert "campaign_stats" in schema_names

    @patch('posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads.LinkedinAdsClient')
    def test_linkedin_ads_source_accounts(self, mock_client_class):
        """Test LinkedIn Ads source for accounts resource."""
        from posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads import linkedin_ads_source
        from posthog.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig

        # Mock the client
        mock_client = Mock()
        mock_client.get_accounts.return_value = [
            {
                "id": "123456789",
                "name": "Test Account",
                "status": "ACTIVE",
                "type": "BUSINESS",
                "currency": "USD",
                "version": {"versionTag": "1.0"}
            }
        ]
        mock_client_class.return_value = mock_client

        config = LinkedinAdsSourceConfig(
            account_id="123456789",
            linkedin_ads_integration_id=str(self.integration.id)
        )

        with patch.object(type(self.integration), 'access_token', new_callable=lambda: property(lambda self: "test_access_token")):
            response = linkedin_ads_source(
                config=config,
                resource_name="accounts",
                team_id=self.team.id,
                should_use_incremental_field=False
            )

        assert response.name == "accounts"
        assert len(response.items) == 1
        assert response.items[0]["id"] == "123456789"
        assert response.items[0]["name"] == "Test Account"
        assert response.primary_keys == ["id"]

    @patch('posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads.LinkedinAdsClient')
    def test_linkedin_ads_source_campaigns(self, mock_client_class):
        """Test LinkedIn Ads source for campaigns resource."""
        from posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads import linkedin_ads_source
        from posthog.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig

        # Mock the client
        mock_client = Mock()
        mock_client.get_campaigns.return_value = [
            {
                "id": "987654321",
                "name": "Test Campaign",
                "account": "urn:li:sponsoredAccount:123456789",
                "status": "ACTIVE",
                "changeAuditStamps": {
                    "created": {"time": 1609459200000},
                    "lastModified": {"time": 1609459200000}
                }
            }
        ]
        mock_client_class.return_value = mock_client

        config = LinkedinAdsSourceConfig(
            account_id="123456789",
            linkedin_ads_integration_id=str(self.integration.id)
        )

        with patch.object(type(self.integration), 'access_token', new_callable=lambda: property(lambda self: "test_access_token")):
            response = linkedin_ads_source(
                config=config,
                resource_name="campaigns",
                team_id=self.team.id,
                should_use_incremental_field=False
            )

        assert response.name == "campaigns"
        assert len(response.items) == 1
        assert response.items[0]["id"] == "987654321"
        assert response.items[0]["name"] == "Test Campaign"
        assert "created_time" in response.items[0]
        assert "last_modified_time" in response.items[0]

    @patch('posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads.LinkedinAdsClient')
    def test_linkedin_ads_source_campaign_stats(self, mock_client_class):
        """Test LinkedIn Ads source for campaign analytics."""
        from posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads import linkedin_ads_source
        from posthog.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig

        # Mock the client
        mock_client = Mock()
        mock_client.get_analytics.return_value = [
            {
                "pivotValues": ["urn:li:sponsoredCampaign:987654321"],
                "dateRange": {
                    "start": {"year": 2025, "month": 8, "day": 1},
                    "end": {"year": 2025, "month": 8, "day": 1}
                },
                "impressions": 1000,
                "clicks": 50,
                "costInUsd": "25.50"
            }
        ]
        mock_client_class.return_value = mock_client

        config = LinkedinAdsSourceConfig(
            account_id="123456789",
            linkedin_ads_integration_id=str(self.integration.id)
        )

        with patch.object(type(self.integration), 'access_token', new_callable=lambda: property(lambda self: "test_access_token")):
            response = linkedin_ads_source(
                config=config,
                resource_name="campaign_stats",
                team_id=self.team.id,
                should_use_incremental_field=True,
                incremental_field="dateRange.start",
                incremental_field_type="Date",
                date_start="2025-08-01"
            )

        assert response.name == "campaign_stats"
        assert len(response.items) == 1
        item = response.items[0]
        assert item["impressions"] == 1000
        assert item["clicks"] == 50
        assert item["cost_in_usd"] == 25.50  # Converted to float
        assert item["campaign_id"] == 987654321  # Extracted from URN
        assert "date_range_start" in item
        assert "date_range_end" in item

    @patch('posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads.LinkedinAdsClient')
    def test_linkedin_ads_source_circuit_breaker_integration(self, mock_client_class):
        """Test circuit breaker integration in the full source flow."""
        from posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads import (
            linkedin_ads_source, 
            _failure_counts, 
            _last_failure_time,
            CIRCUIT_BREAKER_THRESHOLD
        )
        from posthog.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig

        # Clear circuit breaker state
        _failure_counts.clear()
        _last_failure_time.clear()

        # Mock client to always fail
        mock_client = Mock()
        mock_client.get_accounts.side_effect = Exception("API Error")
        mock_client_class.return_value = mock_client

        config = LinkedinAdsSourceConfig(
            account_id="123456789",
            linkedin_ads_integration_id=str(self.integration.id)
        )

        # Trigger failures up to threshold
        for i in range(CIRCUIT_BREAKER_THRESHOLD):
            with patch.object(type(self.integration), 'access_token', new_callable=lambda: property(lambda self: "test_access_token")):
                with pytest.raises(Exception):
                    linkedin_ads_source(
                        config=config,
                        resource_name="accounts",
                        team_id=self.team.id
                    )

        # Next call should fail due to circuit breaker
        with patch.object(type(self.integration), 'access_token', new_callable=lambda: property(lambda self: "test_access_token")):
            with pytest.raises(ValueError, match="Circuit breaker open"):
                linkedin_ads_source(
                    config=config,
                    resource_name="accounts",
                    team_id=self.team.id
                )

    def test_validate_credentials_integration_success(self):
        """Test successful credential validation with real flow."""
        from posthog.temporal.data_imports.sources.linkedin_ads.source import LinkedinAdsSource
        from posthog.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig

        with patch('posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads.LinkedinAdsClient') as mock_client_class:
            mock_client = Mock()
            mock_client.get_accounts.return_value = [
                {"id": "123456789", "name": "Test Account"}
            ]
            mock_client_class.return_value = mock_client

            source = LinkedinAdsSource()
            config = LinkedinAdsSourceConfig(
                account_id="123456789",
                linkedin_ads_integration_id=str(self.integration.id)
            )

            with patch.object(type(self.integration), 'access_token', new_callable=lambda: property(lambda self: "test_access_token")):
                valid, error = source.validate_credentials(config, self.team.id)

            assert valid is True
            assert error is None
