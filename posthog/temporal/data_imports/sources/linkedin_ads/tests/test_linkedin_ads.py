import typing
import datetime as dt

import pytest
from unittest import mock

from posthog.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig
from posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads import (
    LinkedinAdsSchema,
    _convert_date_object_to_date,
    _convert_timestamp_to_date,
    _extract_type_and_id_from_urn,
    _flatten_linkedin_record,
    linkedin_ads_client,
    linkedin_ads_source,
)

from products.data_warehouse.backend.types import IncrementalFieldType


class TestLinkedinAdsHelperFunctions:
    """Test helper functions in linkedin_ads.py."""

    def test_extract_type_and_id_from_urn_valid(self):
        """Test extracting ID and type from valid LinkedIn URN."""
        urn = "urn:li:sponsoredCampaign:12345678"
        result = _extract_type_and_id_from_urn(urn)

        assert result == ("sponsoredCampaign", 12345678)

    def test_convert_date_object_to_date_valid(self):
        """Test converting LinkedIn date object to Python date."""
        date_obj = {"year": 2024, "month": 3, "day": 15}
        result = _convert_date_object_to_date(date_obj)

        assert result == dt.date(2024, 3, 15)

    def test_convert_date_object_to_date_invalid(self):
        """Test converting invalid date object returns None."""
        invalid_cases = [
            {"year": 2024, "month": 3},  # Missing day
            {},  # Empty dict
            None,
        ]

        for invalid_obj in invalid_cases:
            result = _convert_date_object_to_date(invalid_obj)
            assert result is None

    def test_convert_timestamp_to_date_valid(self):
        """Test converting LinkedIn timestamp to date."""
        timestamp_ms = 1709654400000
        last_modified = {"time": timestamp_ms}
        result = _convert_timestamp_to_date(last_modified)

        assert str(result) == "2024-03-05"


class TestFlattenLinkedinRecord:
    """Test _flatten_linkedin_record function."""

    def test_flatten_date_range(self):
        """Test flattening dateRange field."""
        record = {
            "dateRange": {"start": {"year": 2024, "month": 1, "day": 1}, "end": {"year": 2024, "month": 1, "day": 31}}
        }
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["dateRange"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=True,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)

        assert result["date_start"] == dt.date(2024, 1, 1)
        assert result["date_end"] == dt.date(2024, 1, 31)

    def test_flatten_urn_columns(self):
        """Test flattening URN columns."""
        record = {
            "campaignGroup": "urn:li:sponsoredCampaignGroup:123456789",
            "campaign": "urn:li:sponsoredCampaign:987654321",
        }
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["campaignGroup", "campaign"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=False,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)

        assert result["campaign_group_id"] == 123456789
        assert result["campaign_id"] == 987654321

    def test_flatten_integer_fields(self):
        """Test conversion of integer fields."""
        record = {"impressions": 1000, "clicks": 50}
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["impressions", "clicks"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=True,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)

        assert result["impressions"] == 1000
        assert result["clicks"] == 50

    def test_flatten_float_fields(self):
        """Test conversion of float fields."""
        record = {"costInUsd": "25.50"}
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["costInUsd"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=True,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)

        assert result["costInUsd"] == 25.50

    def test_flatten_change_audit_stamps(self):
        """Test flattening changeAuditStamps field."""
        record = {"changeAuditStamps": {"created": {"time": 1709654400000}, "lastModified": {"time": 1709740800000}}}
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["changeAuditStamps"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=False,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)

        assert str(result["created_time"]) == "2024-03-05"
        assert str(result["last_modified_time"]) == "2024-03-06"

    def test_flatten_pivot_values(self):
        """Test flattening pivotValues field."""
        record = {"pivotValues": ["urn:li:sponsoredCampaign:555666777", "urn:li:sponsoredAccount:888999000"]}
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["pivotValues"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=True,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)

        assert result["campaign_id"] == 555666777
        assert result["account_id"] == 888999000

    def test_flatten_complex_objects_to_json(self):
        """Test that complex objects are passed through as-is from API."""
        record = {"targetingCriteria": {"locations": ["US", "CA"], "ages": {"min": 25, "max": 65}}}
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["targetingCriteria"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=False,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)

        # API returns dict objects, pipeline handles JSON conversion later
        assert result["targetingCriteria"]["locations"] == ["US", "CA"]
        assert result["targetingCriteria"]["ages"]["min"] == 25

    def test_flatten_missing_field_returns_none(self):
        """Test missing fields return None."""
        record: dict[str, typing.Any] = {}  # Empty record
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["missing_field"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=False,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)

        assert result["missing_field"] is None


@mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads.Integration")
class TestLinkedinAdsClientFunction:
    """Test linkedin_ads_client function."""

    def test_linkedin_ads_client_no_access_token(self, mock_integration_model):
        """Test client creation with no access token raises error."""
        mock_integration = mock.MagicMock()
        mock_integration.access_token = None
        mock_integration_model.objects.get.return_value = mock_integration

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")

        with pytest.raises(ValueError, match="LinkedIn Ads integration does not have an access token"):
            linkedin_ads_client(config, team_id=789)


@mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads.linkedin_ads_client")
class TestLinkedinAdsSource:
    """Test linkedin_ads_source function."""

    def test_linkedin_ads_source_with_incremental(self, mock_client_func):
        """Test linkedin_ads_source with incremental field."""
        mock_client = mock.MagicMock()
        mock_client.get_data_by_resource.return_value = [
            [{"impressions": 1000, "dateRange": {"start": {"year": 2024, "month": 1, "day": 1}}}]
        ]
        mock_client_func.return_value = mock_client

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")

        result = linkedin_ads_source(
            config=config,
            resource_name="campaign_stats",
            team_id=789,
            should_use_incremental_field=True,
            incremental_field="date_start",
            incremental_field_type=IncrementalFieldType.Date,
            db_incremental_field_last_value=dt.date(2024, 1, 1),
        )

        # Process the rows to trigger the client call
        rows = list(result.items())
        assert len(rows) == 1

        # Verify client was called with correct date parameters
        mock_client.get_data_by_resource.assert_called_once()
        call_args = mock_client.get_data_by_resource.call_args
        assert call_args[1]["date_start"] == "2024-01-01"
