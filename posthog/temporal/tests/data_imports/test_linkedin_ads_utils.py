"""Tests for LinkedIn Ads utility functions."""

import datetime as dt

from unittest.mock import patch

from posthog.temporal.data_imports.sources.linkedin_ads.constants import CIRCUIT_BREAKER_THRESHOLD
from posthog.temporal.data_imports.sources.linkedin_ads.utils import (
    _failure_counts,
    _last_failure_time,
    check_circuit_breaker,
    determine_primary_keys,
    extract_linkedin_id_from_urn,
    flatten_change_audit_stamps,
    flatten_cost_in_usd,
    flatten_data_item,
    flatten_date_range,
    flatten_pivot_values,
    record_failure,
    record_success,
    validate_account_id,
    validate_date_format,
    validate_pivot_value,
)


class TestLinkedInAdsValidators:
    """Test validation utility functions."""

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


class TestLinkedInAdsDataFlattening:
    """Test data flattening utility functions."""

    def test_flatten_date_range(self):
        """Test date range flattening."""
        item = {
            "dateRange": {
                "start": {"year": 2025, "month": 8, "day": 1},
                "end": {"year": 2025, "month": 8, "day": 31}
            }
        }
        flattened = {}

        flatten_date_range(item, flattened)

        assert flattened["date_range_start"] == dt.date(2025, 8, 1)
        assert flattened["date_range_end"] == dt.date(2025, 8, 31)

    def test_flatten_date_range_no_date_range(self):
        """Test date range flattening with no dateRange field."""
        item = {"id": "123"}
        flattened = {}

        flatten_date_range(item, flattened)

        assert "date_range_start" not in flattened
        assert "date_range_end" not in flattened

    def test_flatten_pivot_values_campaign(self):
        """Test pivot values flattening for campaign."""
        item = {
            "pivotValues": ["urn:li:sponsoredCampaign:987654321"]
        }
        flattened = {}

        flatten_pivot_values(item, flattened, "campaign_stats")

        assert flattened["campaign_id"] == 987654321

    def test_flatten_pivot_values_campaign_group(self):
        """Test pivot values flattening for campaign group."""
        item = {
            "pivotValues": ["urn:li:sponsoredCampaignGroup:123456789"]
        }
        flattened = {}

        flatten_pivot_values(item, flattened, "campaign_group_stats")

        assert flattened["campaign_group_id"] == 123456789

    def test_flatten_pivot_values_invalid_id(self):
        """Test pivot values flattening with invalid ID."""
        item = {
            "pivotValues": ["urn:li:sponsoredCampaign:invalid_id"]
        }
        flattened = {}

        flatten_pivot_values(item, flattened, "campaign_stats")

        assert flattened["campaign_id"] == "invalid_id"  # Kept as string

    def test_flatten_cost_in_usd(self):
        """Test cost conversion from string to float."""
        item = {"costInUsd": "25.50"}
        flattened = item.copy()

        flatten_cost_in_usd(item, flattened, "campaign_stats")

        assert flattened["cost_in_usd"] == 25.50
        assert "costInUsd" not in flattened

    def test_flatten_cost_in_usd_invalid(self):
        """Test cost conversion with invalid value."""
        item = {"costInUsd": "invalid"}
        flattened = item.copy()

        flatten_cost_in_usd(item, flattened, "campaign_stats")

        assert flattened["cost_in_usd"] is None

    def test_flatten_change_audit_stamps(self):
        """Test change audit stamps flattening."""
        item = {
            "changeAuditStamps": {
                "created": {"time": 1609459200000},
                "lastModified": {"time": 1609545600000}
            }
        }
        flattened = {}

        flatten_change_audit_stamps(item, flattened)

        assert flattened["created_time"] == 1609459200000
        assert flattened["last_modified_time"] == 1609545600000

    def test_flatten_data_item_complete(self):
        """Test complete data item flattening."""
        item = {
            "id": "123456789",
            "name": "Test Campaign",
            "dateRange": {
                "start": {"year": 2025, "month": 8, "day": 1},
                "end": {"year": 2025, "month": 8, "day": 1}
            },
            "pivotValues": ["urn:li:sponsoredCampaign:987654321"],
            "costInUsd": "25.50",
            "changeAuditStamps": {
                "created": {"time": 1609459200000},
                "lastModified": {"time": 1609545600000}
            }
        }

        flattened = flatten_data_item(item, "campaign_stats")

        assert flattened["id"] == "123456789"
        assert flattened["name"] == "Test Campaign"
        assert flattened["date_range_start"] == dt.date(2025, 8, 1)
        assert flattened["campaign_id"] == 987654321
        assert flattened["cost_in_usd"] == 25.50
        assert flattened["created_time"] == 1609459200000
        assert "costInUsd" not in flattened

    def test_determine_primary_keys_analytics(self):
        """Test primary key determination for analytics data."""
        from posthog.temporal.data_imports.sources.linkedin_ads.schemas import LinkedinAdsResource

        data = [
            {
                "pivotValues": ["urn:li:sponsoredCampaign:123"],
                "date_range_start": dt.date(2025, 8, 1)
            }
        ]

        keys = determine_primary_keys(LinkedinAdsResource.CampaignStats, data)
        assert keys == ["pivotValues", "date_range_start"]

    def test_determine_primary_keys_entity(self):
        """Test primary key determination for entity data."""
        from posthog.temporal.data_imports.sources.linkedin_ads.schemas import LinkedinAdsResource

        data = [{"id": "123456789", "name": "Test"}]

        keys = determine_primary_keys(LinkedinAdsResource.Campaigns, data)
        assert keys == ["id"]

    def test_determine_primary_keys_no_data(self):
        """Test primary key determination with no data."""
        from posthog.temporal.data_imports.sources.linkedin_ads.schemas import LinkedinAdsResource

        keys = determine_primary_keys(LinkedinAdsResource.Campaigns, [])
        assert keys is None
