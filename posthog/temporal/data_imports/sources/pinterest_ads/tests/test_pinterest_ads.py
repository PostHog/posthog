import datetime as dt

import pytest
from unittest import mock

import requests

from posthog.temporal.data_imports.sources.pinterest_ads.pinterest_ads import pinterest_ads_source
from posthog.temporal.data_imports.sources.pinterest_ads.source import PinterestAdsSource
from posthog.temporal.data_imports.sources.pinterest_ads.utils import (
    _chunk_date_range,
    _chunk_list,
    _make_request,
    _normalize_row,
    build_session,
    fetch_account_currency,
    fetch_analytics,
    fetch_entities,
    fetch_entity_ids,
    get_date_range,
)


class TestGetDateRange:
    @pytest.mark.parametrize(
        "last_value,expected_start",
        [
            (dt.datetime(2024, 3, 15, 14, 30, 0), "2024-03-15"),
            (dt.date(2024, 3, 15), "2024-03-15"),
            ("2024-03-15", "2024-03-15"),
        ],
    )
    def test_incremental_values(self, last_value, expected_start):
        start_date, end_date = get_date_range(True, last_value)

        assert start_date == expected_start
        assert end_date == dt.datetime.now().strftime("%Y-%m-%d")

    def test_invalid_string_falls_back_to_default(self):
        start_date, _ = get_date_range(True, "invalid-date")

        assert start_date is not None
        assert start_date != "invalid-date"

    @pytest.mark.parametrize(
        "should_use_incremental,last_value",
        [
            (False, None),
            (True, None),
        ],
    )
    def test_defaults_to_lookback_window(self, should_use_incremental, last_value):
        start_date, end_date = get_date_range(should_use_incremental, last_value)

        assert start_date is not None
        assert end_date == dt.datetime.now().strftime("%Y-%m-%d")


class TestChunkList:
    @pytest.mark.parametrize(
        "items,chunk_size,expected_count,expected_last",
        [
            (list(range(10)), 5, 2, [5, 6, 7, 8, 9]),
            (list(range(7)), 3, 3, [6]),
            ([1, 2, 3], 250, 1, [1, 2, 3]),
            ([], 250, 0, None),
        ],
    )
    def test_chunking(self, items, chunk_size, expected_count, expected_last):
        chunks = _chunk_list(items, chunk_size)
        assert len(chunks) == expected_count
        if expected_last is not None:
            assert chunks[-1] == expected_last


class TestChunkDateRange:
    @pytest.mark.parametrize(
        "start,end,expected_count",
        [
            ("2024-01-01", "2024-03-01", 1),
            ("2024-01-01", "2024-06-30", 3),
            ("2024-01-01", "2024-03-30", 1),
            ("2024-01-01", "2024-01-01", 1),
        ],
    )
    def test_date_chunking(self, start, end, expected_count):
        chunks = _chunk_date_range(start, end)
        assert len(chunks) == expected_count
        assert chunks[0][0] == start
        assert chunks[-1][1] == end


class TestNormalizeRow:
    @pytest.mark.parametrize(
        "input_row,expected",
        [
            (
                {"CAMPAIGN_ID": "123", "SPEND_IN_DOLLAR": 5.0, "DATE": "2024-01-01"},
                {"campaign_id": "123", "spend_in_dollar": 5.0, "date": "2024-01-01"},
            ),
            ({"id": "123", "name": "test"}, {"id": "123", "name": "test"}),
            ({}, {}),
        ],
    )
    def test_normalize(self, input_row, expected):
        assert _normalize_row(input_row) == expected


class TestBuildSession:
    def test_sets_auth_header(self):
        session = build_session("test_token")
        assert session.headers["Authorization"] == "Bearer test_token"
        assert session.headers["Accept"] == "application/json"


class TestFetchEntities:
    @mock.patch("posthog.temporal.data_imports.sources.pinterest_ads.utils._make_request")
    def test_single_page(self, mock_request):
        mock_request.return_value = {"items": [{"id": "1"}, {"id": "2"}], "bookmark": None}
        session = mock.MagicMock()

        result = fetch_entities(session, "acc123", "campaigns")
        assert len(result) == 2
        assert result[0]["id"] == "1"

    @mock.patch("posthog.temporal.data_imports.sources.pinterest_ads.utils._make_request")
    def test_multiple_pages(self, mock_request):
        mock_request.side_effect = [
            {"items": [{"id": "1"}], "bookmark": "next_page"},
            {"items": [{"id": "2"}], "bookmark": None},
        ]
        session = mock.MagicMock()

        result = fetch_entities(session, "acc123", "campaigns")
        assert len(result) == 2
        assert mock_request.call_count == 2

    @mock.patch("posthog.temporal.data_imports.sources.pinterest_ads.utils._make_request")
    def test_empty_response(self, mock_request):
        mock_request.return_value = {"items": [], "bookmark": None}
        session = mock.MagicMock()

        result = fetch_entities(session, "acc123", "campaigns")
        assert result == []


class TestFetchEntityIds:
    @mock.patch("posthog.temporal.data_imports.sources.pinterest_ads.utils.fetch_entities")
    def test_extracts_ids(self, mock_fetch):
        mock_fetch.return_value = [{"id": "1", "name": "a"}, {"id": "2", "name": "b"}]
        session = mock.MagicMock()

        ids = fetch_entity_ids(session, "acc123", "campaign_analytics")
        assert ids == ["1", "2"]
        mock_fetch.assert_called_once_with(session, "acc123", "campaigns")

    @mock.patch("posthog.temporal.data_imports.sources.pinterest_ads.utils.fetch_entities")
    def test_empty_entities(self, mock_fetch):
        mock_fetch.return_value = []
        session = mock.MagicMock()

        ids = fetch_entity_ids(session, "acc123", "campaign_analytics")
        assert ids == []


class TestFetchAccountCurrency:
    @pytest.mark.parametrize(
        "status_code,json_data,expected",
        [
            (200, {"id": "acc123", "currency": "EUR"}, "EUR"),
            (200, {"id": "acc123"}, None),
            (403, {}, None),
            (500, {}, None),
        ],
    )
    def test_currency_fetch(self, status_code, json_data, expected):
        mock_session = mock.MagicMock()
        mock_response = mock.MagicMock()
        mock_response.status_code = status_code
        mock_response.json.return_value = json_data
        mock_session.get.return_value = mock_response

        result = fetch_account_currency(mock_session, "acc123")
        assert result == expected

    def test_returns_none_on_exception(self):
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = Exception("network error")

        result = fetch_account_currency(mock_session, "acc123")
        assert result is None


class TestFetchAnalytics:
    @mock.patch("posthog.temporal.data_imports.sources.pinterest_ads.utils._make_request")
    def test_basic_fetch(self, mock_request):
        mock_request.return_value = [
            {"CAMPAIGN_ID": "1", "DATE": "2024-01-01", "SPEND_IN_DOLLAR": 5.0},
        ]
        session = mock.MagicMock()

        result = fetch_analytics(session, "acc123", "campaign_analytics", ["1"], "2024-01-01", "2024-01-31")
        assert len(result) == 1
        assert result[0]["campaign_id"] == "1"
        assert result[0]["spend_in_dollar"] == 5.0

    @mock.patch("posthog.temporal.data_imports.sources.pinterest_ads.utils._make_request")
    def test_adds_currency_to_rows(self, mock_request):
        mock_request.return_value = [
            {"CAMPAIGN_ID": "1", "DATE": "2024-01-01", "SPEND_IN_DOLLAR": 5.0},
        ]
        session = mock.MagicMock()

        result = fetch_analytics(
            session, "acc123", "campaign_analytics", ["1"], "2024-01-01", "2024-01-31", currency="EUR"
        )
        assert len(result) == 1
        assert result[0]["currency"] == "EUR"

    @mock.patch("posthog.temporal.data_imports.sources.pinterest_ads.utils._make_request")
    def test_no_currency_field_when_none(self, mock_request):
        mock_request.return_value = [
            {"CAMPAIGN_ID": "1", "DATE": "2024-01-01", "SPEND_IN_DOLLAR": 5.0},
        ]
        session = mock.MagicMock()

        result = fetch_analytics(session, "acc123", "campaign_analytics", ["1"], "2024-01-01", "2024-01-31")
        assert "currency" not in result[0]

    @mock.patch("posthog.temporal.data_imports.sources.pinterest_ads.utils._make_request")
    def test_empty_entity_ids(self, mock_request):
        session = mock.MagicMock()

        result = fetch_analytics(session, "acc123", "campaign_analytics", [], "2024-01-01", "2024-01-31")
        assert result == []
        mock_request.assert_not_called()


class TestMakeRequestErrorHandling:
    @pytest.mark.parametrize(
        "status_code",
        [400, 401, 403, 404],
    )
    def test_non_retryable_errors_match_framework(self, status_code):
        """Verify that HTTP errors from _make_request match get_non_retryable_errors patterns."""
        mock_response = mock.MagicMock()
        mock_response.status_code = status_code
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} Client Error: for url: https://api.pinterest.com/v5/test",
            response=mock_response,
        )

        mock_session = mock.MagicMock()
        mock_session.get.return_value = mock_response

        non_retryable_errors = PinterestAdsSource().get_non_retryable_errors()

        with pytest.raises(requests.HTTPError) as exc_info:
            _make_request(mock_session, "https://api.pinterest.com/v5/test")

        error_msg = str(exc_info.value)
        assert any(pattern in error_msg for pattern in non_retryable_errors), (
            f"HTTP {status_code} error message '{error_msg}' does not match any non-retryable pattern"
        )

    @pytest.mark.parametrize("status_code", [200, 201])
    def test_success_returns_json(self, status_code):
        mock_response = mock.MagicMock()
        mock_response.status_code = status_code
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"items": []}

        mock_session = mock.MagicMock()
        mock_session.get.return_value = mock_response

        result = _make_request(mock_session, "https://api.pinterest.com/v5/test")
        assert result == {"items": []}


class TestPinterestAdsSource:
    def test_unknown_endpoint(self):
        with pytest.raises(ValueError, match="Unknown Pinterest Ads endpoint"):
            pinterest_ads_source("acc123", "nonexistent", "token")
