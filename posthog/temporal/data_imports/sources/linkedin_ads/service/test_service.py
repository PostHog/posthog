"""Tests for LinkedIn Ads service layer."""

from datetime import datetime, timedelta

import pytest
from unittest.mock import Mock, patch

from posthog.models import Team
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig

from ..utils.date_handler import LinkedinAdsDateHandler
from .service import LinkedinAdsService


class TestLinkedinAdsService:
    """Test LinkedIn Ads service coordination functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.org = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.org)
        self.integration = Integration.objects.create(
            team=self.team,
            kind="linkedin-ads",
            config={"client_id": "test", "client_secret": "test"},
        )

        self.config = LinkedinAdsSourceConfig(
            account_id="123456789",
            linkedin_ads_integration_id=str(self.integration.id)
        )

    def test_service_initialization(self):
        """Test service initializes correctly."""
        service = LinkedinAdsService(self.config, self.team.id)

        assert service.config == self.config
        assert service.team_id == self.team.id
        assert service.account_id == "123456789"
        assert service.integration_id == str(self.integration.id)

    def test_service_validates_configuration(self):
        """Test service validates configuration on initialization."""
        # Test missing account ID
        invalid_config = LinkedinAdsSourceConfig(
            account_id="",
            linkedin_ads_integration_id=str(self.integration.id)
        )

        with pytest.raises(ValueError, match="LinkedIn account ID is required"):
            LinkedinAdsService(invalid_config, self.team.id)

    def test_service_validates_account_id_format(self):
        """Test service validates account ID format."""
        invalid_config = LinkedinAdsSourceConfig(
            account_id="invalid",
            linkedin_ads_integration_id=str(self.integration.id)
        )

        with pytest.raises(ValueError, match="Invalid LinkedIn account ID format"):
            LinkedinAdsService(invalid_config, self.team.id)

    @patch('posthog.models.integration.Integration.objects.get')
    def test_get_authenticated_client_success(self, mock_get):
        """Test successful client authentication."""
        mock_integration = Mock()
        mock_integration.access_token = "test_token"
        mock_get.return_value = mock_integration

        service = LinkedinAdsService(self.config, self.team.id)

        with patch('posthog.temporal.data_imports.sources.linkedin_ads.service.service.LinkedinAdsClient') as mock_client:
            service._get_authenticated_client()
            mock_client.assert_called_once_with("test_token")

    @patch('posthog.models.integration.Integration.objects.get')
    def test_get_authenticated_client_missing_integration(self, mock_get):
        """Test client authentication with missing integration."""
        mock_get.side_effect = Integration.DoesNotExist()

        service = LinkedinAdsService(self.config, self.team.id)

        with pytest.raises(ValueError, match="LinkedIn Ads integration.*not found"):
            service._get_authenticated_client()

    def test_resource_method_mapping(self):
        """Test resource method mapping works correctly."""
        service = LinkedinAdsService(self.config, self.team.id)

        mock_client = Mock()
        resource_map = service._get_resource_method_map(mock_client)

        # Check that all expected resources are mapped
        expected_resources = [
            "campaign_stats",
            "campaign_group_stats",
            "campaigns",
            "campaign_groups",
            "accounts"
        ]

        for resource in expected_resources:
            assert resource in resource_map
            method, pivot = resource_map[resource]
            assert callable(method)


class TestLinkedinAdsDateHandler:
    """Test LinkedIn Ads date handling functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.date_handler = LinkedinAdsDateHandler()

    def test_date_handler_initialization(self):
        """Test date handler initializes with correct defaults."""
        assert self.date_handler.max_date_range_days == 1825  # 5 years

    def test_validate_date_format_valid(self):
        """Test date format validation with valid dates."""
        valid_dates = ["2023-01-01", "2023-12-31", "2024-02-29"]

        for date_str in valid_dates:
            start_date, end_date = self.date_handler.calculate_date_range(date_str, date_str)
            assert start_date is not None
            assert end_date is not None

    def test_validate_date_format_invalid(self):
        """Test date format validation with invalid dates."""
        with pytest.raises(ValueError, match="Invalid date_start format"):
            self.date_handler.calculate_date_range("invalid-date", None)

    def test_default_date_range(self):
        """Test default date range calculation."""
        start_date, end_date = self.date_handler.calculate_date_range()

        # Should return a range of approximately 30 days
        delta = (end_date - start_date).days
        assert 29 <= delta <= 31

    def test_linkedin_date_range_formatting(self):
        """Test LinkedIn API date range formatting."""
        start_date = datetime(2023, 1, 15)
        end_date = datetime(2023, 1, 20)

        formatted = self.date_handler.format_linkedin_date_range(start_date, end_date)
        expected = "(start:(year:2023,month:1,day:15),end:(year:2023,month:1,day:20))"

        assert formatted == expected

    def test_incremental_date_calculation(self):
        """Test incremental date calculation."""
        last_value = "2023-01-15"
        result = self.date_handler.calculate_incremental_date_range(last_value)

        assert result == "2023-01-15"

    def test_incremental_date_with_sync_frequency(self):
        """Test incremental date calculation with sync frequency limit."""
        last_value = "2020-01-01"  # Very old date
        sync_interval = timedelta(days=7)  # Weekly sync

        result = self.date_handler.calculate_incremental_date_range(last_value, sync_interval)

        # Should not go back further than sync frequency allows
        result_date = datetime.strptime(result, "%Y-%m-%d")
        now = datetime.now()
        delta = (now - result_date).days

        # Should be limited by sync frequency (around 7 days)
        assert delta <= 10  # Allow some buffer
