from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from parameterized import parameterized

from posthog.temporal.data_imports.sources.tiktok_ads.settings import MAX_TIKTOK_DAYS_TO_QUERY
from posthog.temporal.data_imports.sources.tiktok_ads.tiktok_ads import get_tiktok_resource
from posthog.temporal.data_imports.sources.tiktok_ads.utils import (
    flatten_tiktok_report_record,
    flatten_tiktok_reports,
    generate_date_chunks,
    get_incremental_date_range,
)


class TestTikTokAdsHelpers:
    """Test suite for TikTok Ads helper functions."""

    def test_flatten_tiktok_report_record_nested(self):
        """Test flattening nested TikTok report structure."""
        nested_record = {
            "dimensions": {"campaign_id": "123456", "stat_time_day": "2025-09-27"},
            "metrics": {"clicks": "947", "impressions": "23241", "spend": "125.50"},
        }

        result = flatten_tiktok_report_record(nested_record)

        expected = {
            "campaign_id": "123456",
            "stat_time_day": "2025-09-27",
            "clicks": "947",
            "impressions": "23241",
            "spend": "125.50",
        }

        assert result == expected

    def test_flatten_tiktok_report_record_flat(self):
        """Test flattening already flat record (entity endpoints)."""
        flat_record = {"campaign_id": "123456", "campaign_name": "Test Campaign", "status": "ENABLE"}

        result = flatten_tiktok_report_record(flat_record)
        assert result == flat_record

    def test_flatten_tiktok_reports(self):
        """Test batch flattening of TikTok reports."""
        reports = [
            {"dimensions": {"campaign_id": "123"}, "metrics": {"clicks": "100"}},
            {"dimensions": {"campaign_id": "456"}, "metrics": {"clicks": "200"}},
        ]

        result = flatten_tiktok_reports(reports)

        expected = [{"campaign_id": "123", "clicks": "100"}, {"campaign_id": "456", "clicks": "200"}]

        assert result == expected

    @parameterized.expand(
        [
            ("no_incremental", False, None, 30),
            ("with_datetime", True, datetime(2025, 9, 1), 30),
            ("with_date_string", True, "2025-09-01", 30),
            ("with_recent_date", True, datetime.now() - timedelta(days=2), 7),
            ("with_old_date", True, datetime.now() - timedelta(days=60), 60),
        ]
    )
    def test_get_incremental_date_range(self, name, should_use_incremental, last_value, expected_days_back):
        """Test incremental date range calculation."""
        start_date, end_date = get_incremental_date_range(should_use_incremental, last_value)

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        days_diff = (end_dt - start_dt).days
        assert days_diff <= expected_days_back + 1

    def test_get_incremental_date_range_parse_error(self):
        """Test date range calculation with invalid last value."""
        start_date, end_date = get_incremental_date_range(True, "invalid_date")

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        days_diff = (end_dt - start_dt).days

        assert days_diff <= 31

    @parameterized.expand(
        [
            ("single_chunk", "2025-09-01", "2025-09-15", 30, 1),
            ("two_chunks", "2025-09-01", "2025-10-15", 30, 2),
            ("three_chunks", "2025-09-01", "2025-11-30", 30, 3),
            ("exact_boundary", "2025-09-01", "2025-10-01", 30, 1),
        ]
    )
    def test_generate_date_chunks(self, name, start_date, end_date, chunk_days, expected_chunks):
        """Test date chunk generation."""
        chunks = generate_date_chunks(start_date, end_date, chunk_days)

        assert len(chunks) == expected_chunks

        for i, (chunk_start, chunk_end) in enumerate(chunks):
            chunk_start_dt = datetime.strptime(chunk_start, "%Y-%m-%d")
            chunk_end_dt = datetime.strptime(chunk_end, "%Y-%m-%d")

            assert (chunk_end_dt - chunk_start_dt).days <= chunk_days

            if i < len(chunks) - 1:
                next_chunk_start = datetime.strptime(chunks[i + 1][0], "%Y-%m-%d")
                assert (next_chunk_start - chunk_end_dt).days == 1


class TestGetResource:
    """Test suite for resource configuration generation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.advertiser_id = "test_advertiser_123"

    def test_get_tiktok_resource_unknown_endpoint(self):
        """Test error handling for unknown endpoint."""
        with pytest.raises(ValueError, match="Unknown endpoint: invalid_endpoint"):
            get_tiktok_resource("invalid_endpoint", self.advertiser_id, False)

    def test_get_tiktok_resource_entity_endpoint(self):
        """Test resource configuration for entity endpoint (campaigns)."""
        resource = get_tiktok_resource("campaigns", self.advertiser_id, False)

        assert resource["name"] == "campaigns"
        assert resource["table_name"] == "campaigns"
        assert resource["primary_key"] == ["campaign_id"]
        assert resource["write_disposition"] == "replace"

        assert resource["endpoint"]["params"]["advertiser_id"] == self.advertiser_id

    def test_get_tiktok_resource_report_endpoint_incremental(self):
        """Test resource configuration for report endpoint with incremental sync."""
        last_value = datetime.now() - timedelta(days=5)
        resource = get_tiktok_resource("campaign_report", self.advertiser_id, True, last_value)

        assert resource["name"] == "campaign_report"
        assert resource["table_name"] == "campaign_report"
        assert resource["primary_key"] == ["campaign_id", "stat_time_day"]
        assert resource["write_disposition"]["disposition"] == "merge"

        assert "start_date" in resource["endpoint"]["params"]
        assert "end_date" in resource["endpoint"]["params"]

    def test_get_tiktok_resource_report_endpoint_full_refresh(self):
        """Test resource configuration for report endpoint with full refresh."""
        resource = get_tiktok_resource("campaign_report", self.advertiser_id, False)

        assert "start_date" in resource["endpoint"]["params"]
        assert "end_date" in resource["endpoint"]["params"]

        start_date = datetime.strptime(resource["endpoint"]["params"]["start_date"], "%Y-%m-%d")
        end_date = datetime.strptime(resource["endpoint"]["params"]["end_date"], "%Y-%m-%d")
        days_diff = (end_date - start_date).days

        assert days_diff > 0

    def test_get_tiktok_resource_with_date_chunking(self):
        """Test resource configuration with date chunking for large ranges."""
        old_date = datetime.now() - timedelta(days=60)
        resource = get_tiktok_resource("campaign_report", self.advertiser_id, True, old_date)

        # Verify that start_date and end_date are set to the first chunk
        assert "start_date" in resource["endpoint"]["params"]
        assert "end_date" in resource["endpoint"]["params"]

        # The date range should be limited to MAX_TIKTOK_DAYS_TO_QUERY (30 days)
        start_date = datetime.strptime(resource["endpoint"]["params"]["start_date"], "%Y-%m-%d")
        end_date = datetime.strptime(resource["endpoint"]["params"]["end_date"], "%Y-%m-%d")
        days_diff = (end_date - start_date).days
        assert days_diff <= MAX_TIKTOK_DAYS_TO_QUERY


class TestTikTokAdsSource:
    """Test suite for main TikTok Ads source function."""

    def setup_method(self):
        """Set up test fixtures."""
        self.advertiser_id = "test_advertiser_123"
        self.team_id = 123
        self.job_id = str(uuid4())
        self.access_token = "test_access_token"
