import pytest
from unittest import mock

import gspread

from posthog.temporal.data_imports.sources.generated_configs import GoogleSheetsSourceConfig
from posthog.temporal.data_imports.sources.google_sheets.google_sheets import (
    _PERMISSION_DENIED_MESSAGE,
    _get_worksheet,
    get_schemas,
    google_sheets_source,
)
from posthog.temporal.data_imports.sources.google_sheets.source import GoogleSheetsSource


def test_get_worksheet_backoff():
    with (
        mock.patch(
            "posthog.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
        ) as mock_google_sheets_client,
        mock.patch("posthog.temporal.data_imports.sources.google_sheets.google_sheets.time"),
    ):
        mock_spreadsheet = mock.MagicMock()
        mock_get_worksheet_by_id = mock.MagicMock()

        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "error": {
                "code": 429,
                "message": "Rate limit exceeded",
                "status": "RESOURCE_EXHAUSTED",
            }
        }

        mock_get_worksheet_by_id.side_effect = gspread.exceptions.APIError(mock_response)

        instance = mock_google_sheets_client.return_value
        instance.open_by_url.return_value = mock_spreadsheet
        mock_spreadsheet.get_worksheet_by_id = mock_get_worksheet_by_id

        with pytest.raises(gspread.exceptions.APIError):
            _get_worksheet("url", 1)

        assert mock_get_worksheet_by_id.call_count == 10


@pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
def test_get_worksheet_retries_transient_api_errors(status_code):
    """Transient API errors (quota 429s and 5xx server errors like
    "[500]: Internal error encountered.") should be retried with backoff, not
    re-raised on the first occurrence."""
    with (
        mock.patch(
            "posthog.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
        ) as mock_google_sheets_client,
        mock.patch("posthog.temporal.data_imports.sources.google_sheets.google_sheets.time"),
    ):
        mock_spreadsheet = mock.MagicMock()
        mock_get_worksheet_by_id = mock.MagicMock()

        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "error": {
                "code": status_code,
                "message": "Internal error encountered.",
                "status": "INTERNAL",
            }
        }

        mock_get_worksheet_by_id.side_effect = gspread.exceptions.APIError(mock_response)

        instance = mock_google_sheets_client.return_value
        instance.open_by_url.return_value = mock_spreadsheet
        mock_spreadsheet.get_worksheet_by_id = mock_get_worksheet_by_id

        # Use a unique worksheet id per status code to avoid the module-level TTLCache
        with pytest.raises(gspread.exceptions.APIError):
            _get_worksheet("transient-url", status_code)

        assert mock_get_worksheet_by_id.call_count == 10


def test_get_worksheet_does_not_retry_non_transient_api_error():
    """A non-transient API error (e.g. 400) should be raised immediately without
    burning through the retry budget."""
    with (
        mock.patch(
            "posthog.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
        ) as mock_google_sheets_client,
        mock.patch("posthog.temporal.data_imports.sources.google_sheets.google_sheets.time"),
    ):
        mock_spreadsheet = mock.MagicMock()
        mock_get_worksheet_by_id = mock.MagicMock()

        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "error": {"code": 400, "message": "Bad request", "status": "INVALID_ARGUMENT"}
        }

        mock_get_worksheet_by_id.side_effect = gspread.exceptions.APIError(mock_response)

        instance = mock_google_sheets_client.return_value
        instance.open_by_url.return_value = mock_spreadsheet
        mock_spreadsheet.get_worksheet_by_id = mock_get_worksheet_by_id

        with pytest.raises(gspread.exceptions.APIError):
            _get_worksheet("non-transient-url", 400)

        assert mock_get_worksheet_by_id.call_count == 1


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


@pytest.mark.parametrize(
    "call_site",
    [
        pytest.param(
            lambda: get_schemas(
                GoogleSheetsSourceConfig(spreadsheet_url="https://docs.google.com/spreadsheets/d/fake")
            ),
            id="get_schemas",
        ),
        # Use a unique url/id to avoid the module-level TTLCache returning a prior result
        pytest.param(lambda: _get_worksheet("permission-error-url", 999), id="_get_worksheet"),
    ],
)
def test_reraises_permission_error_with_message(call_site):
    with mock.patch(
        "posthog.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
    ) as mock_google_sheets_client:
        instance = mock_google_sheets_client.return_value
        instance.open_by_url.side_effect = PermissionError()

        with pytest.raises(PermissionError) as exc_info:
            call_site()

        assert "Spreadsheet access denied" in str(exc_info.value)


def test_google_sheets_source_reads_blank_cells_as_null():
    config = GoogleSheetsSourceConfig(spreadsheet_url="https://docs.google.com/spreadsheets/d/fake")

    mock_worksheet = mock.MagicMock()
    mock_worksheet.get_all_values.return_value = [["id", "NumericColumnWithBlanks"]]
    mock_worksheet.get_all_records.return_value = [
        {"id": 1, "NumericColumnWithBlanks": 1.5},
        {"id": 2, "NumericColumnWithBlanks": None},
    ]

    with (
        mock.patch(
            "posthog.temporal.data_imports.sources.google_sheets.google_sheets.get_schemas",
            return_value=[("sheet1", 123)],
        ),
        mock.patch(
            "posthog.temporal.data_imports.sources.google_sheets.google_sheets._get_worksheet",
            return_value=mock_worksheet,
        ),
    ):
        response = google_sheets_source(config, "sheet1", db_incremental_field_last_value=None)
        list(response.items())

    mock_worksheet.get_all_records.assert_called_once_with(default_blank=None)


def test_permission_error_is_non_retryable():
    """The message we re-raise from gspread's bare PermissionError must be a
    substring match for one of the source's non-retryable error keys, otherwise
    we'd retry a 403 forever."""
    source = GoogleSheetsSource()
    non_retryable_errors = source.get_non_retryable_errors()

    raised = PermissionError(_PERMISSION_DENIED_MESSAGE)
    error_msg = str(raised)

    assert any(key in error_msg for key in non_retryable_errors)


def test_not_found_api_error_is_non_retryable():
    """gspread raises a 404 APIError when the spreadsheet has been deleted/moved — it
    must match a non-retryable pattern so we stop retrying a permanent failure."""
    mock_response = mock.MagicMock()
    mock_response.json.return_value = {
        "error": {"code": 404, "message": "Requested entity was not found.", "status": "NOT_FOUND"}
    }
    error_msg = str(gspread.exceptions.APIError(mock_response))

    non_retryable_errors = GoogleSheetsSource().get_non_retryable_errors()
    assert any(key in error_msg for key in non_retryable_errors), (
        f"Google Sheets 404 error {error_msg!r} did not match any non-retryable pattern"
    )
