"""Tests for TikTok Ads utility functions."""

from datetime import date, datetime, timedelta

import pytest

from parameterized import parameterized

from posthog.temporal.data_imports.sources.tiktok_ads.utils import (
    TikTokAdsPaginator,
    flatten_tiktok_report_record,
    flatten_tiktok_reports,
    generate_date_chunks,
    get_incremental_date_range,
    is_report_endpoint,
)


class TestFlattenFunctions:
    """Test suite for TikTok report flattening functions."""

    def test_flatten_tiktok_report_record_nested_structure(self):
        """Test flattening nested TikTok report structure with dimensions and metrics."""
        nested_record = {
            "dimensions": {"campaign_id": "123456789", "stat_time_day": "2025-09-27", "adgroup_id": "987654321"},
            "metrics": {"clicks": "947", "impressions": "23241", "spend": "125.50", "cpm": "5.40", "ctr": "4.08"},
        }

        result = flatten_tiktok_report_record(nested_record)

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

        result = flatten_tiktok_report_record(flat_record)
        assert result == flat_record

    def test_flatten_tiktok_report_record_missing_dimensions(self):
        """Test flattening record with metrics but no dimensions."""
        record_with_metrics_only = {"metrics": {"clicks": "100", "impressions": "1000"}}

        result = flatten_tiktok_report_record(record_with_metrics_only)

        expected = {"metrics": {"clicks": "100", "impressions": "1000"}}

        assert result == expected

    def test_flatten_tiktok_report_record_missing_metrics(self):
        """Test flattening record with dimensions but no metrics."""
        record_with_dimensions_only = {"dimensions": {"campaign_id": "123", "stat_time_day": "2025-09-27"}}

        result = flatten_tiktok_report_record(record_with_dimensions_only)

        expected = {"dimensions": {"campaign_id": "123", "stat_time_day": "2025-09-27"}}

        assert result == expected

    def test_flatten_tiktok_report_record_empty_nested_objects(self):
        """Test flattening record with empty dimensions and metrics."""
        record_with_empty_nested = {"dimensions": {}, "metrics": {}}

        result = flatten_tiktok_report_record(record_with_empty_nested)
        assert result == {}

    def test_flatten_tiktok_report_record_non_dict_input(self):
        """Test flattening with non-dictionary input."""
        non_dict_inputs = ["string_input", 123, ["list", "input"], None]

        for input_value in non_dict_inputs:
            result = flatten_tiktok_report_record(input_value)
            assert result == input_value

    def test_flatten_tiktok_reports_batch_processing(self):
        """Test batch flattening of multiple TikTok reports."""
        reports = [
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

        result = flatten_tiktok_reports(reports)

        expected = [
            {"campaign_id": "123", "stat_time_day": "2025-09-27", "clicks": "100", "impressions": "1000"},
            {"campaign_id": "456", "stat_time_day": "2025-09-27", "clicks": "200", "impressions": "2000"},
            {"campaign_id": "789", "campaign_name": "Test Campaign", "status": "ENABLE"},
        ]

        assert result == expected

    def test_flatten_tiktok_reports_empty_list(self):
        """Test batch flattening with empty list."""
        result = flatten_tiktok_reports([])
        assert result == []


class TestDateRangeFunctions:
    """Test suite for date range calculation functions."""

    @parameterized.expand(
        [
            ("no_incremental_no_last_value", False, None, 30),
            ("no_incremental_with_last_value", False, datetime.now() - timedelta(days=5), 30),
            ("incremental_no_last_value", True, None, 30),
            ("incremental_with_recent_datetime", True, datetime.now() - timedelta(days=2), 7),
            ("incremental_with_old_datetime", True, datetime.now() - timedelta(days=60), 60),
            ("incremental_with_recent_date", True, date.today() - timedelta(days=3), 7),
            ("incremental_with_date_string", True, "2025-09-25", 7),
            ("incremental_with_iso_string", True, (datetime.now() - timedelta(days=4)).isoformat(), 7),
        ]
    )
    def test_get_incremental_date_range_scenarios(self, name, should_use_incremental, last_value, expected_max_days):
        """Test various incremental date range calculation scenarios."""
        start_date, end_date = get_incremental_date_range(should_use_incremental, last_value)

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        assert end_dt.date() == datetime.now().date()

        days_diff = (end_dt - start_dt).days
        assert days_diff <= expected_max_days + 1

    def test_get_incremental_date_range_invalid_date_string(self):
        """Test date range calculation with invalid date string."""
        start_date, end_date = get_incremental_date_range(True, "invalid_date_string")

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        days_diff = (end_dt - start_dt).days

        assert days_diff <= 31

    def test_get_incremental_date_range_future_date(self):
        """Test date range calculation with future date (should use 7-day minimum)."""
        future_date = datetime.now() + timedelta(days=10)
        start_date, end_date = get_incremental_date_range(True, future_date)

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        days_diff = (end_dt - start_dt).days

        assert days_diff == 7

    @parameterized.expand(
        [
            ("single_chunk_short_range", "2025-09-01", "2025-09-15", 30, 1),
            ("single_chunk_exact_boundary", "2025-09-01", "2025-10-01", 30, 1),
            ("two_chunks", "2025-09-01", "2025-10-15", 30, 2),
            ("three_chunks", "2025-09-01", "2025-11-30", 30, 3),
            ("small_chunk_size", "2025-09-01", "2025-09-15", 7, 2),
            ("same_day", "2025-09-01", "2025-09-01", 30, 1),
        ]
    )
    def test_generate_date_chunks_scenarios(self, name, start_date, end_date, chunk_days, expected_chunks):
        """Test date chunk generation for various scenarios."""
        chunks = generate_date_chunks(start_date, end_date, chunk_days)

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
        with pytest.raises(ValueError):
            generate_date_chunks("invalid-date", "2025-09-15", 30)

    def test_generate_date_chunks_end_before_start(self):
        """Test date chunk generation when end date is before start date."""
        chunks = generate_date_chunks("2025-09-15", "2025-09-01", 30)
        assert len(chunks) == 0


class TestTikTokAdsPaginator:
    """Test suite for TikTokAdsPaginator class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.paginator = TikTokAdsPaginator()

    def test_paginator_initialization(self):
        """Test paginator initial state."""
        assert self.paginator.current_page == 1
        assert self.paginator.has_next_page is False
        assert self.paginator.total_pages == 0
        assert self.paginator.total_number == 0
        assert self.paginator.page_size == 0

    def test_update_from_response_first_page_with_more(self):
        """Test paginator update from first page response with more pages."""
        response_data = {"data": {"page_info": {"page": 1, "page_size": 100, "total_page": 3, "total_number": 250}}}

        has_next = self.paginator.update_from_response(response_data)

        assert has_next is True
        assert self.paginator.has_next_page is True
        assert self.paginator.current_page == 2
        assert self.paginator.total_pages == 3
        assert self.paginator.total_number == 250
        assert self.paginator.page_size == 100

    def test_update_from_response_last_page(self):
        """Test paginator update from last page response."""
        response_data = {"data": {"page_info": {"page": 3, "page_size": 100, "total_page": 3, "total_number": 250}}}

        has_next = self.paginator.update_from_response(response_data)

        assert has_next is False
        assert self.paginator.has_next_page is False
        assert self.paginator.current_page == 1
        assert self.paginator.total_pages == 3

    def test_update_from_response_single_page(self):
        """Test paginator update from single page response."""
        response_data = {"data": {"page_info": {"page": 1, "page_size": 50, "total_page": 1, "total_number": 50}}}

        has_next = self.paginator.update_from_response(response_data)

        assert has_next is False
        assert self.paginator.has_next_page is False
        assert self.paginator.current_page == 1

    def test_update_from_response_missing_page_info(self):
        """Test paginator update with missing page_info."""
        response_data = {"data": {}}

        has_next = self.paginator.update_from_response(response_data)

        assert has_next is False
        assert self.paginator.has_next_page is False

    def test_update_from_response_missing_data(self):
        """Test paginator update with missing data key."""
        response_data = {}

        has_next = self.paginator.update_from_response(response_data)

        assert has_next is False
        assert self.paginator.has_next_page is False

    def test_update_from_response_exception_handling(self):
        """Test paginator handles malformed response gracefully."""
        malformed_responses = [
            None,
            "string_response",
            {"data": "not_a_dict"},
            {"data": {"page_info": "not_a_dict"}},
        ]

        for response in malformed_responses:
            has_next = self.paginator.update_from_response(response)
            assert has_next is False
            assert self.paginator.has_next_page is False


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
        result = is_report_endpoint(endpoint_name)
        assert result == expected_is_report
