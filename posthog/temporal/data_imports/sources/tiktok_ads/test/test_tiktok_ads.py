from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.sources.tiktok_ads.tiktok_ads import get_tiktok_resource, tiktok_ads_source
from posthog.temporal.data_imports.sources.tiktok_ads.utils import TikTokDateRangeManager, TikTokReportResource


class TestTikTokAdsHelpers:
    """Test suite for TikTok Ads helper functions."""

    def test_flatten_tiktok_report_record_nested(self):
        """Test flattening nested TikTok report structure."""
        nested_record = {
            "dimensions": {"campaign_id": "123456", "stat_time_day": "2025-09-27"},
            "metrics": {"clicks": "947", "impressions": "23241", "spend": "125.50"},
        }

        result = TikTokReportResource.transform_analytics_reports([nested_record])[0]

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

        result = TikTokReportResource.transform_entity_reports([flat_record])[0]
        # The transform_entity_reports method adds current_status when status field exists
        expected = flat_record.copy()
        expected["current_status"] = "ACTIVE"
        assert result == expected

    def test_flatten_tiktok_reports(self):
        """Test batch flattening of TikTok reports."""
        reports = [
            {"dimensions": {"campaign_id": "123"}, "metrics": {"clicks": "100"}},
            {"dimensions": {"campaign_id": "456"}, "metrics": {"clicks": "200"}},
        ]

        result = TikTokReportResource.transform_analytics_reports(reports)

        expected = [{"campaign_id": "123", "clicks": "100"}, {"campaign_id": "456", "clicks": "200"}]

        assert result == expected

    @parameterized.expand(
        [
            ("no_incremental", False, None, 365),  # Uses MAX_TIKTOK_DAYS_FOR_REPORT_ENDPOINTS
            ("with_datetime", True, datetime.now() - timedelta(days=30), 30),
            ("with_date_string", True, (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"), 30),
            ("with_recent_date", True, datetime.now() - timedelta(days=2), 7),
            ("with_old_date", True, datetime.now() - timedelta(days=60), 60),
        ]
    )
    def test_get_incremental_date_range(self, name, should_use_incremental, last_value, expected_days_back):
        """Test incremental date range calculation."""
        start_date, end_date = TikTokDateRangeManager.get_incremental_range(should_use_incremental, last_value)

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        days_diff = (end_dt - start_dt).days
        assert days_diff <= expected_days_back + 1

    def test_get_incremental_date_range_parse_error(self):
        """Test date range calculation with invalid last value."""
        start_date, end_date = TikTokDateRangeManager.get_incremental_range(True, "invalid_date")

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        days_diff = (end_dt - start_dt).days

        assert days_diff <= 365  # Falls back to full range

    @parameterized.expand(
        [
            (
                "single_chunk",
                (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                30,
                1,
            ),
            (
                "two_chunks",
                (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                30,
                2,
            ),
            (
                "three_chunks",
                (datetime.now() - timedelta(days=89)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                30,
                3,
            ),
            (
                "exact_boundary",
                (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                30,
                1,
            ),
        ]
    )
    def test_generate_date_chunks(self, name, start_date, end_date, chunk_days, expected_chunks):
        """Test date chunk generation."""
        chunks = TikTokDateRangeManager.generate_chunks(start_date, end_date, chunk_days)

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
        self.advertiser_id = "123456789"

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
        resource = get_tiktok_resource("campaign_report", self.advertiser_id, True)

        assert resource["name"] == "campaign_report"
        assert resource["table_name"] == "campaign_report"
        assert resource["primary_key"] == ["campaign_id", "stat_time_day"]
        assert isinstance(resource["write_disposition"], dict)
        write_disposition = resource["write_disposition"]
        assert write_disposition["disposition"] == "merge"
        assert write_disposition["strategy"] == "upsert"

        assert "start_date" in resource["endpoint"]["params"]
        assert "end_date" in resource["endpoint"]["params"]

    def test_get_tiktok_resource_report_endpoint_full_refresh(self):
        """Test resource configuration for report endpoint with full refresh."""
        resource = get_tiktok_resource("campaign_report", self.advertiser_id, False)

        assert "start_date" in resource["endpoint"]["params"]
        assert "end_date" in resource["endpoint"]["params"]

        # When no dates are provided in the base resource, they should be template placeholders
        assert resource["endpoint"]["params"]["start_date"] == "{start_date}"
        assert resource["endpoint"]["params"]["end_date"] == "{end_date}"

    def test_get_tiktok_resource_with_date_chunking(self):
        """Test resource configuration shows template placeholders for date chunking."""
        resource = get_tiktok_resource("campaign_report", self.advertiser_id, True)

        assert "start_date" in resource["endpoint"]["params"]
        assert "end_date" in resource["endpoint"]["params"]

        # Base resource should have template placeholders that will be filled by chunking logic
        assert resource["endpoint"]["params"]["start_date"] == "{start_date}"
        assert resource["endpoint"]["params"]["end_date"] == "{end_date}"


class TestTikTokAdsSource:
    """Test suite for main TikTok Ads source function."""

    def setup_method(self):
        """Set up test fixtures."""
        self.advertiser_id = "123456789"
        self.team_id = 123
        self.job_id = str(uuid4())
        self.access_token = "test_access_token"

    @parameterized.expand(
        [
            ("campaigns", False, None),
            ("ad_groups", False, None),
            ("ads", False, None),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.tiktok_ads.tiktok_ads.rest_api_resources")
    def test_tiktok_ads_source_entity_endpoints(
        self, endpoint, should_use_incremental, last_value, mock_rest_api_resources
    ):
        """Test source function for entity endpoints (non-report)."""
        # Mock the rest_api_resources function to return a list with a mock DLT resource
        mock_dlt_resource = Mock()
        mock_dlt_resource.__iter__ = Mock(return_value=iter([{"campaign_id": "123", "name": "Test Campaign"}]))
        mock_rest_api_resources.return_value = [mock_dlt_resource]

        result = tiktok_ads_source(
            advertiser_id=self.advertiser_id,
            endpoint=endpoint,
            team_id=self.team_id,
            job_id=self.job_id,
            access_token=self.access_token,
            db_incremental_field_last_value=last_value,
            should_use_incremental_field=should_use_incremental,
        )

        assert result.name == endpoint
        assert result.items is not None
        assert result.partition_count == 1

    @parameterized.expand(
        [
            ("campaign_report", False, None),
            ("ad_group_report", False, None),
            ("ad_report", False, None),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.tiktok_ads.tiktok_ads.rest_api_resources")
    def test_tiktok_ads_source_report_endpoints_full_refresh(
        self, endpoint, should_use_incremental, last_value, mock_rest_api_resources
    ):
        """Test source function for report endpoints with full refresh."""
        # Mock the rest_api_resources function to return a list with a mock DLT resource
        mock_dlt_resource = Mock()
        mock_dlt_resource.__iter__ = Mock(return_value=iter([{"campaign_id": "123", "clicks": "100"}]))
        mock_rest_api_resources.return_value = [mock_dlt_resource]

        result = tiktok_ads_source(
            advertiser_id=self.advertiser_id,
            endpoint=endpoint,
            team_id=self.team_id,
            job_id=self.job_id,
            access_token=self.access_token,
            db_incremental_field_last_value=last_value,
            should_use_incremental_field=should_use_incremental,
        )

        assert result.name == endpoint
        assert result.items is not None
        assert result.partition_count == 1

    @parameterized.expand(
        [
            ("campaign_report", True, datetime.now() - timedelta(days=5)),
            ("ad_group_report", True, (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")),
            ("ad_report", True, datetime.now() - timedelta(days=10)),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.tiktok_ads.tiktok_ads.rest_api_resources")
    def test_tiktok_ads_source_report_endpoints_incremental(
        self, endpoint, should_use_incremental, last_value, mock_rest_api_resources
    ):
        """Test source function for report endpoints with incremental sync."""
        # Mock the rest_api_resources function to return a list with a mock DLT resource
        mock_dlt_resource = Mock()
        mock_dlt_resource.__iter__ = Mock(return_value=iter([{"campaign_id": "123", "clicks": "100"}]))
        mock_rest_api_resources.return_value = [mock_dlt_resource]

        result = tiktok_ads_source(
            advertiser_id=self.advertiser_id,
            endpoint=endpoint,
            team_id=self.team_id,
            job_id=self.job_id,
            access_token=self.access_token,
            db_incremental_field_last_value=last_value,
            should_use_incremental_field=should_use_incremental,
        )

        assert result.name == endpoint
        assert result.items is not None
        assert result.partition_count == 1

    def test_tiktok_ads_source_invalid_endpoint(self):
        """Test source function with invalid endpoint."""
        with pytest.raises(KeyError):
            tiktok_ads_source(
                advertiser_id=self.advertiser_id,
                endpoint="invalid_endpoint",
                team_id=self.team_id,
                job_id=self.job_id,
                access_token=self.access_token,
                db_incremental_field_last_value=None,
                should_use_incremental_field=False,
            )
