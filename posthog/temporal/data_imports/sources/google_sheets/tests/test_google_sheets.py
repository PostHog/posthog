import pytest
from unittest import mock

import gspread

from posthog.temporal.data_imports.sources.google_sheets.google_sheets import (
    _get_worksheet,
    cache,
    get_schema_incremental_fields,
    get_schemas,
)


def _quota_exceeded_api_error() -> gspread.exceptions.APIError:
    mock_response = mock.MagicMock()
    mock_response.json.return_value = {
        "error": {
            "code": 429,
            "message": (
                "Quota exceeded for quota metric 'Read requests' and limit "
                "'Read requests per minute' of service 'sheets.googleapis.com' "
                "for consumer 'project_number:951095883823'."
            ),
            "status": "RESOURCE_EXHAUSTED",
        }
    }
    return gspread.exceptions.APIError(mock_response)


@pytest.fixture(autouse=True)
def clear_worksheet_cache():
    cache.clear()
    yield
    cache.clear()


def test_get_worksheet_backoff():
    with (
        mock.patch(
            "posthog.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
        ) as mock_google_sheets_client,
        mock.patch("posthog.temporal.data_imports.sources.google_sheets.google_sheets.time"),
    ):
        mock_spreadsheet = mock.MagicMock()
        mock_get_worksheet_by_id = mock.MagicMock()

        mock_get_worksheet_by_id.side_effect = _quota_exceeded_api_error()

        instance = mock_google_sheets_client.return_value
        instance.open_by_url.return_value = mock_spreadsheet
        mock_spreadsheet.get_worksheet_by_id = mock_get_worksheet_by_id

        with pytest.raises(gspread.exceptions.APIError):
            _get_worksheet("url", 1)

        assert mock_get_worksheet_by_id.call_count == 10


def test_get_worksheet_caching():
    with (
        mock.patch(
            "posthog.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
        ) as mock_google_sheets_client,
    ):
        _get_worksheet("url", 1)
        _get_worksheet("url", 1)
        _get_worksheet("url", 1)

        # It should only have 1 call, the others should be returning the cached value
        assert mock_google_sheets_client.call_count == 1

        _get_worksheet("url", 2)
        _get_worksheet("url", 2)
        _get_worksheet("url", 2)

        # It should now have 2 calls, we've changed one of the arguments, but the second/third calls should be cached
        assert mock_google_sheets_client.call_count == 2


def test_get_schemas_retries_on_quota_exceeded():
    """Regression: get_schemas previously did not retry on 429, causing sync_new_schemas
    to fail the whole import when the shared Google Cloud project hit its per-minute read quota."""
    with (
        mock.patch(
            "posthog.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
        ) as mock_google_sheets_client,
        mock.patch("posthog.temporal.data_imports.sources.google_sheets.google_sheets.time"),
    ):
        mock_spreadsheet = mock.MagicMock()
        mock_worksheets = mock.MagicMock()
        mock_worksheets.side_effect = _quota_exceeded_api_error()

        instance = mock_google_sheets_client.return_value
        instance.open_by_url.return_value = mock_spreadsheet
        mock_spreadsheet.worksheets = mock_worksheets

        config = mock.MagicMock()
        config.spreadsheet_url = "https://docs.google.com/spreadsheets/d/abc/edit"

        with pytest.raises(gspread.exceptions.APIError):
            get_schemas(config)

        assert mock_worksheets.call_count == 10


def test_get_schema_incremental_fields_retries_on_quota_exceeded():
    """Regression: get_schema_incremental_fields called worksheet.get_all_values without
    the 429 retry wrapper, so a quota-exceeded response at that step would fail
    sync_new_schemas even though the existing _get_worksheet retry logic covered
    the preceding call."""
    with (
        mock.patch(
            "posthog.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
        ) as mock_google_sheets_client,
        mock.patch("posthog.temporal.data_imports.sources.google_sheets.google_sheets.time"),
    ):
        mock_worksheet = mock.MagicMock()
        mock_worksheet.id = 1
        mock_worksheet.title = "Sheet1"

        mock_spreadsheet = mock.MagicMock()
        mock_spreadsheet.worksheets.return_value = [mock_worksheet]
        mock_spreadsheet.get_worksheet_by_id.return_value = mock_worksheet

        instance = mock_google_sheets_client.return_value
        instance.open_by_url.return_value = mock_spreadsheet

        mock_worksheet.get_all_values.side_effect = _quota_exceeded_api_error()

        config = mock.MagicMock()
        config.spreadsheet_url = "https://docs.google.com/spreadsheets/d/abc/edit"

        with pytest.raises(gspread.exceptions.APIError):
            get_schema_incremental_fields(config, "sheet1")

        assert mock_worksheet.get_all_values.call_count == 10
