"""Tests for LinkedIn Ads utilities and shared components."""

from datetime import date

from .schemas import LinkedinAdsResource
from .types import LinkedinAccountType, LinkedinAnalyticsType, LinkedinCampaignType
from .utils import (
    determine_primary_keys,
    flatten_data_item,
    validate_account_id,
    validate_date_format,
    validate_pivot_value,
)


class TestValidationFunctions:
    """Test utility validation functions."""

    def test_validate_account_id_valid(self):
        """Test account ID validation with valid IDs."""
        valid_ids = [
            "123456",
            "123456789",
            "123456789012345",  # 15 digits
        ]

        for account_id in valid_ids:
            assert validate_account_id(account_id) is True

    def test_validate_account_id_invalid(self):
        """Test account ID validation with invalid IDs."""
        invalid_ids = [
            "",
            "12345",  # Too short
            "1234567890123456",  # Too long
            "12345a",  # Contains letters
            "123-456",  # Contains special chars
        ]

        for account_id in invalid_ids:
            assert validate_account_id(account_id) is False

    def test_validate_date_format_valid(self):
        """Test date format validation with valid dates."""
        valid_dates = [
            "2023-01-01",
            "2023-12-31",
            "2024-02-29",  # Leap year
        ]

        for date_str in valid_dates:
            assert validate_date_format(date_str) is True

    def test_validate_date_format_invalid(self):
        """Test date format validation with invalid dates."""
        invalid_dates = [
            "",
            "2023-13-01",  # Invalid month
            "2023-01-32",  # Invalid day
            "2023/01/01",  # Wrong format
            "01-01-2023",  # Wrong order
            "2023-1-1",  # Missing leading zeros
        ]

        for date_str in invalid_dates:
            assert validate_date_format(date_str) is False

    def test_validate_pivot_value_valid(self):
        """Test pivot value validation with valid pivots."""
        valid_pivots = ["CAMPAIGN", "CAMPAIGN_GROUP", "CREATIVE", "ACCOUNT"]

        for pivot in valid_pivots:
            assert validate_pivot_value(pivot) is True

    def test_validate_pivot_value_invalid(self):
        """Test pivot value validation with invalid pivots."""
        invalid_pivots = [
            "",
            "campaign",  # Wrong case
            "INVALID",
            "CAMPAIGNS",  # Plural
        ]

        for pivot in invalid_pivots:
            assert validate_pivot_value(pivot) is False


class TestDataFlattening:
    """Test data flattening functionality."""

    def test_flatten_analytics_data(self):
        """Test flattening analytics data with date ranges."""
        analytics_item = {
            "impressions": 1000,
            "clicks": 50,
            "costInUsd": "25.50",
            "dateRange": {"start": {"year": 2023, "month": 1, "day": 15}, "end": {"year": 2023, "month": 1, "day": 15}},
            "pivotValues": ["urn:li:sponsoredCampaign:123456789"],
        }

        result = flatten_data_item(analytics_item, "campaign_stats")

        # Check flattened fields
        assert result["impressions"] == 1000
        assert result["clicks"] == 50
        assert result["cost_in_usd"] == 25.5  # Converted to float
        assert result["date_range_start"] == date(2023, 1, 15)
        assert result["date_range_end"] == date(2023, 1, 15)
        assert result["campaign_id"] == "123456789"

    def test_flatten_campaign_data(self):
        """Test flattening campaign data."""
        campaign_item = {
            "id": "987654321",
            "name": "Test Campaign",
            "status": "ACTIVE",
            "account": "urn:li:sponsoredAccount:123456789",
            "changeAuditStamps": {"created": {"time": 1609459200000}, "lastModified": {"time": 1609459200000}},
        }

        result = flatten_data_item(campaign_item, "campaigns")

        # Check basic fields are preserved
        assert result["id"] == "987654321"
        assert result["name"] == "Test Campaign"
        assert result["status"] == "ACTIVE"

    def test_determine_primary_keys_campaigns(self):
        """Test primary key determination for campaigns."""
        flattened_data = [{"id": "123", "name": "Campaign 1"}, {"id": "456", "name": "Campaign 2"}]

        primary_keys = determine_primary_keys("campaigns", flattened_data)
        assert primary_keys == ["id"]

    def test_determine_primary_keys_analytics(self):
        """Test primary key determination for analytics data."""
        flattened_data = [
            {"campaign_id": "123", "date_range_start": date(2023, 1, 15), "impressions": 1000},
            {"campaign_id": "456", "date_range_start": date(2023, 1, 15), "impressions": 2000},
        ]

        primary_keys = determine_primary_keys("campaign_stats", flattened_data)
        # Analytics should have composite primary key
        assert primary_keys is not None
        assert "campaign_id" in primary_keys
        assert "date_range_start" in primary_keys

    def test_determine_primary_keys_empty_data(self):
        """Test primary key determination with empty data."""
        primary_keys = determine_primary_keys("campaigns", [])
        assert primary_keys is None


class TestTypeDefinitions:
    """Test type definitions and schemas."""

    def test_linkedin_ads_resource_enum(self):
        """Test LinkedIn Ads resource enum values."""
        assert LinkedinAdsResource.Accounts.value == "accounts"
        assert LinkedinAdsResource.Campaigns.value == "campaigns"
        assert LinkedinAdsResource.CampaignGroups.value == "campaign_groups"
        assert LinkedinAdsResource.CampaignStats.value == "campaign_stats"
        assert LinkedinAdsResource.CampaignGroupStats.value == "campaign_group_stats"

    def test_type_definitions_exist(self):
        """Test that key type definitions exist."""
        # Just verify they're importable
        assert LinkedinAccountType is not None
        assert LinkedinCampaignType is not None
        assert LinkedinAnalyticsType is not None
