import datetime as dt

import pytest
from unittest import mock

from posthog.temporal.data_imports.sources.pinterest_ads.pinterest_ads import pinterest_ads_source
from posthog.temporal.data_imports.sources.pinterest_ads.utils import (
    _chunk_date_range,
    _chunk_list,
    _normalize_row,
    build_session,
    fetch_analytics,
    fetch_entities,
    fetch_entity_ids,
    get_date_range,
    validate_ad_account,
)


class TestGetDateRange:
    def test_with_datetime(self):
        last_value = dt.datetime(2024, 3, 15, 14, 30, 0)
        start_date, end_date = get_date_range(True, last_value)

        assert start_date == "2024-03-15"
        assert end_date == dt.datetime.now().strftime("%Y-%m-%d")

    def test_with_date(self):
        last_value = dt.date(2024, 3, 15)
        start_date, end_date = get_date_range(True, last_value)

        assert start_date == "2024-03-15"

    def test_with_string(self):
        start_date, end_date = get_date_range(True, "2024-03-15")

        assert start_date == "2024-03-15"

    def test_with_invalid_string(self):
        start_date, end_date = get_date_range(True, "invalid-date")

        assert start_date is not None
        assert start_date != "invalid-date"

    def test_no_incremental(self):
        start_date, end_date = get_date_range(False)

        assert start_date is not None
        assert end_date == dt.datetime.now().strftime("%Y-%m-%d")

    def test_none_value(self):
        start_date, end_date = get_date_range(True, None)

        assert start_date is not None


class TestChunkList:
    def test_exact_chunks(self):
        items = list(range(10))
        chunks = _chunk_list(items, 5)
        assert len(chunks) == 2
        assert chunks[0] == [0, 1, 2, 3, 4]
        assert chunks[1] == [5, 6, 7, 8, 9]

    def test_partial_last_chunk(self):
        items = list(range(7))
        chunks = _chunk_list(items, 3)
        assert len(chunks) == 3
        assert chunks[2] == [6]

    def test_single_chunk(self):
        items = [1, 2, 3]
        chunks = _chunk_list(items, 250)
        assert len(chunks) == 1

    def test_empty_list(self):
        assert _chunk_list([], 250) == []


class TestChunkDateRange:
    def test_within_limit(self):
        chunks = _chunk_date_range("2024-01-01", "2024-03-01")
        assert len(chunks) == 1
        assert chunks[0] == ("2024-01-01", "2024-03-01")

    def test_exceeds_limit(self):
        chunks = _chunk_date_range("2024-01-01", "2024-06-30")
        assert len(chunks) == 3
        assert chunks[0][0] == "2024-01-01"
        assert chunks[-1][1] == "2024-06-30"

    def test_exact_limit(self):
        chunks = _chunk_date_range("2024-01-01", "2024-03-30")
        assert len(chunks) == 1

    def test_single_day(self):
        chunks = _chunk_date_range("2024-01-01", "2024-01-01")
        assert len(chunks) == 1
        assert chunks[0] == ("2024-01-01", "2024-01-01")


class TestNormalizeRow:
    def test_uppercase_to_lowercase(self):
        row = {"CAMPAIGN_ID": "123", "SPEND_IN_DOLLAR": 5.0, "DATE": "2024-01-01"}
        result = _normalize_row(row)
        assert result == {"campaign_id": "123", "spend_in_dollar": 5.0, "date": "2024-01-01"}

    def test_already_lowercase(self):
        row = {"id": "123", "name": "test"}
        assert _normalize_row(row) == row

    def test_empty_row(self):
        assert _normalize_row({}) == {}


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
    def test_empty_entity_ids(self, mock_request):
        session = mock.MagicMock()

        result = fetch_analytics(session, "acc123", "campaign_analytics", [], "2024-01-01", "2024-01-31")
        assert result == []
        mock_request.assert_not_called()


class TestValidateAdAccount:
    @mock.patch("posthog.temporal.data_imports.sources.pinterest_ads.utils.build_session")
    def test_valid_account(self, mock_build):
        mock_session = mock.MagicMock()
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_session.get.return_value = mock_response
        mock_build.return_value = mock_session

        is_valid, error = validate_ad_account("token", "acc123")
        assert is_valid is True
        assert error is None

    @mock.patch("posthog.temporal.data_imports.sources.pinterest_ads.utils.build_session")
    def test_forbidden(self, mock_build):
        mock_session = mock.MagicMock()
        mock_response = mock.MagicMock()
        mock_response.status_code = 403
        mock_session.get.return_value = mock_response
        mock_build.return_value = mock_session

        is_valid, error = validate_ad_account("token", "acc123")
        assert is_valid is False
        assert "Access denied" in error

    @mock.patch("posthog.temporal.data_imports.sources.pinterest_ads.utils.build_session")
    def test_not_found(self, mock_build):
        mock_session = mock.MagicMock()
        mock_response = mock.MagicMock()
        mock_response.status_code = 404
        mock_session.get.return_value = mock_response
        mock_build.return_value = mock_session

        is_valid, error = validate_ad_account("token", "acc123")
        assert is_valid is False
        assert "not found" in error


class TestPinterestAdsSource:
    def test_unknown_endpoint(self):
        with pytest.raises(ValueError, match="Unknown Pinterest Ads endpoint"):
            pinterest_ads_source("acc123", "nonexistent", "token")
