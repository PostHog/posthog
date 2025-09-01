"""Integration tests for LinkedIn Ads source."""

import pytest
from unittest.mock import Mock, patch

from posthog.models import Team
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig

from .linkedin_ads import get_incremental_fields, get_schemas, linkedin_ads_source
from .source import LinkedinAdsSource
from .utils.utils import record_failure


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
        from .utils.utils import _failure_counts, _last_failure_time

        _failure_counts.clear()
        _last_failure_time.clear()

    def teardown_method(self):
        """Clean up after each test."""
        # Clear circuit breaker state after each test
        from .utils.utils import _failure_counts, _last_failure_time

        _failure_counts.clear()
        _last_failure_time.clear()

    def _mock_access_token(self):
        """Helper method to mock access_token property."""
        return patch.object(
            type(self.integration), "access_token", new_callable=lambda: property(lambda self: "test_access_token")
        )

    def test_get_schemas_success(self):
        """Test successful schema retrieval."""
        schemas = get_schemas()

        assert len(schemas) > 0
        schema_names = list(schemas.keys())
        assert "accounts" in schema_names
        assert "campaigns" in schema_names
        assert "campaign_stats" in schema_names

    def test_get_incremental_fields(self):
        """Test incremental fields retrieval."""
        incremental_fields = get_incremental_fields()

        assert "campaign_stats" in incremental_fields
        assert "campaign_group_stats" in incremental_fields

        # Check field structure
        campaign_stats_fields = incremental_fields["campaign_stats"]
        assert len(campaign_stats_fields) > 0
        field_name, field_type = campaign_stats_fields[0]
        assert field_name == "dateRange.start"

    @patch("posthog.temporal.data_imports.sources.linkedin_ads.client.LinkedinAdsClient")
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

        config = LinkedinAdsSourceConfig(account_id="123456789", linkedin_ads_integration_id=str(self.integration.id))

        with self._mock_access_token():
            response = linkedin_ads_source(
                config=config, resource_name="accounts", team_id=self.team.id, should_use_incremental_field=False
            )

        assert response.name == "accounts"
        assert len(response.items) == 1
        assert response.items[0]["id"] == "123456789"
        assert response.items[0]["name"] == "Test Account"

    @patch("posthog.temporal.data_imports.sources.linkedin_ads.client.LinkedinAdsClient")
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

        config = LinkedinAdsSourceConfig(account_id="123456789", linkedin_ads_integration_id=str(self.integration.id))

        with self._mock_access_token():
            response = linkedin_ads_source(
                config=config, resource_name="campaigns", team_id=self.team.id, should_use_incremental_field=False
            )

        assert response.name == "campaigns"
        assert len(response.items) == 1
        assert response.items[0]["id"] == "987654321"
        assert response.items[0]["name"] == "Test Campaign"

    @patch("posthog.temporal.data_imports.sources.linkedin_ads.client.LinkedinAdsClient")
    def test_linkedin_ads_source_analytics(self, mock_client_class):
        """Test LinkedIn Ads source for analytics data."""
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

        config = LinkedinAdsSourceConfig(account_id="123456789", linkedin_ads_integration_id=str(self.integration.id))

        with self._mock_access_token():
            response = linkedin_ads_source(
                config=config, resource_name="campaign_stats", team_id=self.team.id, should_use_incremental_field=False
            )

        assert response.name == "campaign_stats"
        assert len(response.items) == 1

        # Check flattened data
        item = response.items[0]
        assert item["impressions"] == 1000
        assert item["clicks"] == 50
        assert item["cost_in_usd"] == 25.5
        assert item["campaign_id"] == "987654321"

    def test_linkedin_ads_source_circuit_breaker(self):
        """Test circuit breaker functionality."""
        config = LinkedinAdsSourceConfig(account_id="123456789", linkedin_ads_integration_id=str(self.integration.id))

        # Circuit breaker should be open after too many failures
        # This would require setting up failure state first

        # Simulate multiple failures
        for _ in range(5):
            record_failure("123456789")

        # Now the circuit breaker should prevent requests
        with self._mock_access_token():
            with pytest.raises(ValueError, match="Circuit breaker open"):
                linkedin_ads_source(config=config, resource_name="accounts", team_id=self.team.id)

    @patch("posthog.temporal.data_imports.sources.linkedin_ads.client.LinkedinAdsClient")
    def test_validate_credentials_success(self, mock_client_class):
        """Test successful credential validation."""
        mock_client = Mock()
        mock_client.get_accounts.return_value = [{"id": "123456789", "name": "Test Account"}]
        mock_client_class.return_value = mock_client

        source = LinkedinAdsSource()
        config = LinkedinAdsSourceConfig(account_id="123456789", linkedin_ads_integration_id=str(self.integration.id))

        with self._mock_access_token():
            valid, error = source.validate_credentials(config, self.team.id)

        assert valid is True
        assert error is None

    def test_validate_credentials_missing_account_id(self):
        """Test credential validation with missing account ID."""
        source = LinkedinAdsSource()
        config = LinkedinAdsSourceConfig(account_id="", linkedin_ads_integration_id=str(self.integration.id))

        valid, error = source.validate_credentials(config, self.team.id)
        assert valid is False
        assert "Account ID is required" in error

    def test_validate_credentials_invalid_account_id_format(self):
        """Test credential validation with invalid account ID format."""
        source = LinkedinAdsSource()
        config = LinkedinAdsSourceConfig(account_id="invalid", linkedin_ads_integration_id=str(self.integration.id))

        valid, error = source.validate_credentials(config, self.team.id)
        assert valid is False
        assert "Invalid account ID format" in error
