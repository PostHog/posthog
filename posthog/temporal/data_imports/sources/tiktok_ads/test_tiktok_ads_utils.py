"""Tests for TikTok Ads utility functions."""

from datetime import date, datetime, timedelta
from typing import Any, cast

import pytest
from unittest.mock import Mock

from parameterized import parameterized

from posthog.temporal.data_imports.sources.tiktok_ads.utils import (
    TikTokAdsAPIError,
    TikTokAdsPaginator,
    TikTokDateRangeManager,
    TikTokReportResource,
)


class TestFlattenFunctions:
    """Test suite for TikTok report flattening functions."""

    def test_flatten_tiktok_report_record_nested_structure(self):
        """Test flattening nested TikTok report structure with dimensions and metrics."""
        nested_record = {
            "dimensions": {"campaign_id": "123456789", "stat_time_day": "2025-09-27", "adgroup_id": "987654321"},
            "metrics": {"clicks": "947", "impressions": "23241", "spend": "125.50", "cpm": "5.40", "ctr": "4.08"},
        }

        result = TikTokReportResource.flatten_record(nested_record)

        expected = {
            "campaign_id": "123456789",
            "stat_time_day": "2025-09-27",
            "adgroup_id": "987654321",
            "clicks": "947",
            "impressions": "23241",
            "spend": "125.50",
            "cpm": "5.40",
            "ctr": "4.08",
        }

        assert result == expected

    def test_flatten_tiktok_report_record_flat_structure(self):
        """Test flattening already flat record (entity endpoints like campaigns)."""
        flat_record = {
            "campaign_id": "123456789",
            "campaign_name": "Test Campaign",
            "status": "ENABLE",
            "create_time": "2025-09-01 10:00:00",
            "modify_time": "2025-09-27 15:30:00",
        }

        result = TikTokReportResource.flatten_record(flat_record)
        assert result == flat_record

    def test_flatten_tiktok_report_record_missing_dimensions(self):
        """Test flattening record with metrics but no dimensions."""
        record_with_metrics_only = {"metrics": {"clicks": "100", "impressions": "1000"}}

        result = TikTokReportResource.flatten_record(record_with_metrics_only)

        expected = {"metrics": {"clicks": "100", "impressions": "1000"}}

        assert result == expected

    def test_flatten_tiktok_report_record_missing_metrics(self):
        """Test flattening record with dimensions but no metrics."""
        record_with_dimensions_only = {"dimensions": {"campaign_id": "123", "stat_time_day": "2025-09-27"}}

        result = TikTokReportResource.flatten_record(record_with_dimensions_only)

        expected = {"dimensions": {"campaign_id": "123", "stat_time_day": "2025-09-27"}}

        assert result == expected

    def test_flatten_tiktok_report_record_empty_nested_objects(self):
        """Test flattening record with empty dimensions and metrics."""
        record_with_empty_nested: dict[str, dict] = {"dimensions": {}, "metrics": {}}

        result = TikTokReportResource.flatten_record(record_with_empty_nested)
        assert result == {}

    def test_flatten_tiktok_report_record_non_dict_input(self):
        """Test flattening with non-dictionary input."""
        non_dict_inputs: list[object] = ["string_input", 123, ["list", "input"], None]

        for input_value in non_dict_inputs:
            result = TikTokReportResource.flatten_record(cast(dict[str, Any], input_value))
            assert result == input_value

    def test_flatten_tiktok_reports_batch_processing(self):
        """Test batch flattening of multiple TikTok reports."""
        reports: list[dict[str, Any]] = [
            {
                "dimensions": {"campaign_id": "123", "stat_time_day": "2025-09-27"},
                "metrics": {"clicks": "100", "impressions": "1000"},
            },
            {
                "dimensions": {"campaign_id": "456", "stat_time_day": "2025-09-27"},
                "metrics": {"clicks": "200", "impressions": "2000"},
            },
            {"campaign_id": "789", "campaign_name": "Test Campaign", "status": "ENABLE"},
        ]

        result = TikTokReportResource.flatten_records(reports)

        expected = [
            {"campaign_id": "123", "stat_time_day": "2025-09-27", "clicks": "100", "impressions": "1000"},
            {"campaign_id": "456", "stat_time_day": "2025-09-27", "clicks": "200", "impressions": "2000"},
            {"campaign_id": "789", "campaign_name": "Test Campaign", "status": "ENABLE"},
        ]

        assert result == expected

    def test_flatten_tiktok_reports_empty_list(self):
        """Test batch flattening with empty list."""
        result = TikTokReportResource.flatten_records([])
        assert result == []


class TestDateRangeFunctions:
    """Test suite for date range calculation functions."""

    @parameterized.expand(
        [
            ("no_incremental_no_last_value", False, None, 365),  # Uses MAX_TIKTOK_DAYS_FOR_REPORT_ENDPOINTS (3 years)
            ("no_incremental_with_last_value", False, datetime.now() - timedelta(days=5), 365),
            ("incremental_no_last_value", True, None, 365),
            ("incremental_with_recent_datetime", True, datetime.now() - timedelta(days=2), 7),
            ("incremental_with_old_datetime", True, datetime.now() - timedelta(days=60), 60),
            ("incremental_with_recent_date", True, date.today() - timedelta(days=3), 7),
            (
                "incremental_with_date_string",
                True,
                (datetime.now() - timedelta(days=12)).strftime("%Y-%m-%d"),
                12,
            ),  # 12 days ago
            ("incremental_with_iso_string", True, (datetime.now() - timedelta(days=4)).isoformat(), 7),
        ]
    )
    def test_get_incremental_date_range_scenarios(self, name, should_use_incremental, last_value, expected_max_days):
        """Test various incremental date range calculation scenarios."""
        start_date, end_date = TikTokDateRangeManager.get_incremental_range(should_use_incremental, last_value)

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        assert end_dt.date() in [today, yesterday]

        days_diff = (end_dt - start_dt).days
        assert days_diff <= expected_max_days + 1

    def test_get_incremental_date_range_invalid_date_string(self):
        """Test date range calculation with invalid date string."""
        start_date, end_date = TikTokDateRangeManager.get_incremental_range(True, "invalid_date_string")

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        days_diff = (end_dt - start_dt).days

        assert days_diff <= 365  # Falls back to full range (3 years)

    def test_get_incremental_date_range_future_date(self):
        """Test date range calculation with future date (should use future date as start)."""
        future_date = datetime.now() + timedelta(days=10)
        start_date, end_date = TikTokDateRangeManager.get_incremental_range(True, future_date)

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        days_diff = (end_dt - start_dt).days

        # Should use the future date as start, so negative days
        assert days_diff == -10

    @parameterized.expand(
        [
            (
                "single_chunk_short_range",
                (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d"),
                (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d"),
                30,
                1,
            ),
            (
                "single_chunk_exact_boundary",
                (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                30,
                1,
            ),
            (
                "two_chunks",
                (datetime.now() - timedelta(days=59)).strftime("%Y-%m-%d"),
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
                "small_chunk_size",
                (datetime.now() - timedelta(days=13)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                7,
                2,
            ),
            (
                "exact_30_days",
                (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                30,
                1,
            ),
            ("same_day", datetime.now().strftime("%Y-%m-%d"), datetime.now().strftime("%Y-%m-%d"), 30, 1),
        ]
    )
    def test_generate_date_chunks_scenarios(self, name, start_date, end_date, chunk_days, expected_chunks):
        """Test date chunk generation for various scenarios."""
        chunks = TikTokDateRangeManager.generate_chunks(start_date, end_date, chunk_days)

        assert len(chunks) == expected_chunks

        first_chunk_start = chunks[0][0]
        last_chunk_end = chunks[-1][1]
        assert first_chunk_start == start_date
        assert last_chunk_end == end_date

        for i, (chunk_start, chunk_end) in enumerate(chunks):
            chunk_start_dt = datetime.strptime(chunk_start, "%Y-%m-%d")
            chunk_end_dt = datetime.strptime(chunk_end, "%Y-%m-%d")

            assert (chunk_end_dt - chunk_start_dt).days <= chunk_days

            if i < len(chunks) - 1:
                next_chunk_start = datetime.strptime(chunks[i + 1][0], "%Y-%m-%d")
                assert (next_chunk_start - chunk_end_dt).days == 1

    def test_generate_date_chunks_invalid_date_format(self):
        """Test date chunk generation with invalid date format."""
        valid_end_date = datetime.now().strftime("%Y-%m-%d")
        with pytest.raises(ValueError):
            TikTokDateRangeManager.generate_chunks("invalid-date", valid_end_date, 30)

    def test_generate_date_chunks_end_before_start(self):
        """Test date chunk generation when end date is before start date."""
        start_date = datetime.now().strftime("%Y-%m-%d")
        end_date = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
        chunks = TikTokDateRangeManager.generate_chunks(start_date, end_date, 30)
        assert len(chunks) == 0


class TestTikTokAdsPaginator:
    """Test suite for TikTokAdsPaginator class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.paginator = TikTokAdsPaginator()

    def _create_mock_response(self, response_data: dict[Any, Any]) -> Mock:
        """Create a mock Response object with the given JSON data."""
        mock_response = Mock()
        mock_response.json.return_value = {"code": 0, **response_data}
        return mock_response

    def test_paginator_initialization(self):
        """Test paginator initial state."""
        assert self.paginator.current_page == 1
        assert self.paginator.has_next_page is False
        assert self.paginator.total_pages == 0
        assert self.paginator.total_number == 0
        assert self.paginator.page_size == 0

    def test_update_state_first_page_with_more(self):
        """Test paginator update from first page response with more pages."""
        response_data = {"data": {"page_info": {"page": 1, "page_size": 100, "total_page": 3, "total_number": 250}}}
        mock_response = self._create_mock_response(response_data)

        self.paginator.update_state(mock_response)

        assert self.paginator.has_next_page is True
        assert self.paginator.current_page == 2
        assert self.paginator.total_pages == 3
        assert self.paginator.total_number == 250
        assert self.paginator.page_size == 100

    def test_update_state_last_page(self):
        """Test paginator update from last page response."""
        response_data = {"data": {"page_info": {"page": 3, "page_size": 100, "total_page": 3, "total_number": 250}}}
        mock_response = self._create_mock_response(response_data)

        self.paginator.update_state(mock_response)

        assert self.paginator.has_next_page is False
        assert self.paginator.current_page == 1
        assert self.paginator.total_pages == 3

    def test_update_state_single_page(self):
        """Test paginator update from single page response."""
        response_data = {"data": {"page_info": {"page": 1, "page_size": 50, "total_page": 1, "total_number": 50}}}
        mock_response = self._create_mock_response(response_data)

        self.paginator.update_state(mock_response)

        assert self.paginator.has_next_page is False
        assert self.paginator.current_page == 1

    def test_update_state_missing_page_info(self):
        """Test paginator update with missing page_info."""
        response_data: dict[str, dict] = {"data": {}}
        mock_response = self._create_mock_response(response_data)

        self.paginator.update_state(mock_response)

        assert self.paginator.has_next_page is False

    def test_update_state_missing_data(self):
        """Test paginator update with missing data key."""
        response_data: dict[str, Any] = {}
        mock_response = self._create_mock_response(response_data)

        self.paginator.update_state(mock_response)

        assert self.paginator.has_next_page is False

    def test_update_state_exception_handling(self):
        """Test paginator handles malformed response gracefully."""
        malformed_responses = [
            {"data": "not_a_dict"},
            {"data": {"page_info": "not_a_dict"}},
        ]

        for response_data in malformed_responses:
            mock_response = self._create_mock_response(cast(dict[Any, Any], response_data))
            with pytest.raises(TikTokAdsAPIError, match="Failed to parse TikTok API response"):
                self.paginator.update_state(mock_response)

        # Test with response that raises exception on json()
        mock_response = Mock()
        mock_response.json.side_effect = Exception("JSON decode error")
        with pytest.raises(TikTokAdsAPIError, match="Failed to parse TikTok API response"):
            self.paginator.update_state(mock_response)

    @parameterized.expand(
        [
            ("qps_limit_error", 40100, "App reaches the QPS limit 20", True),
            ("rate_limit_error", 40001, "Rate limit exceeded", False),  # Auth error - not retryable
            ("validation_error", 40002, "Invalid parameter", False),  # Client error - not retryable
            ("server_error", 50000, "Internal server error", True),
            ("service_unavailable", 50001, "Service temporarily unavailable", True),
        ]
    )
    def test_update_state_api_error_codes(self, name, api_code, message, should_be_retryable):
        """Test paginator handling of various TikTok API error codes."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": api_code,
            "message": message,
            "data": {},
            "request_id": "test-request-id",
        }

        if should_be_retryable:
            with pytest.raises(TikTokAdsAPIError) as exc_info:
                self.paginator.update_state(mock_response)

            assert str(api_code) in str(exc_info.value)
            assert message in str(exc_info.value)
            assert exc_info.value.api_code == api_code
        else:
            with pytest.raises(ValueError) as value_exc_info:
                self.paginator.update_state(mock_response)

            assert "non-retryable" in str(value_exc_info.value)
            assert str(api_code) in str(value_exc_info.value)


class TestTikTokAdsAPIError:
    """Test suite for TikTokAdsAPIError exception class."""

    def test_tiktok_ads_api_error_basic_creation(self):
        """Test basic TikTokAdsAPIError creation."""
        error = TikTokAdsAPIError("Test error message")

        assert str(error) == "Test error message"
        assert error.api_code is None
        assert error.response is None

    def test_tiktok_ads_api_error_with_api_code(self):
        """Test TikTokAdsAPIError with API code."""
        error = TikTokAdsAPIError("QPS limit reached", api_code=40100)

        assert str(error) == "QPS limit reached"
        assert error.api_code == 40100
        assert error.response is None

    def test_tiktok_ads_api_error_with_response(self):
        """Test TikTokAdsAPIError with response object."""
        mock_response = Mock()
        mock_response.status_code = 200

        error = TikTokAdsAPIError("API error", api_code=40100, response=mock_response)

        assert str(error) == "API error"
        assert error.api_code == 40100
        assert error.response == mock_response


class TestHelperFunctions:
    """Test suite for utility helper functions."""

    @parameterized.expand(
        [
            ("campaign_report", True),
            ("ad_group_report", True),
            ("ad_report", True),
            ("campaigns", False),
            ("ad_groups", False),
            ("ads", False),
            ("unknown_endpoint", False),
        ]
    )
    def test_is_report_endpoint(self, endpoint_name, expected_is_report):
        """Test identification of report endpoints."""
        result = TikTokReportResource.is_report_endpoint(endpoint_name)
        assert result == expected_is_report
