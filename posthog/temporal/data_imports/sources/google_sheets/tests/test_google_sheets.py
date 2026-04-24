import pytest
from unittest import mock

import gspread

from posthog.temporal.data_imports.sources.generated_configs import GoogleSheetsSourceConfig
from posthog.temporal.data_imports.sources.google_sheets.google_sheets import _get_worksheet, get_schemas
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


def test_get_schemas_reraises_permission_error_with_message():
    with mock.patch(
        "posthog.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
    ) as mock_google_sheets_client:
        instance = mock_google_sheets_client.return_value
        instance.open_by_url.side_effect = PermissionError()

        config = GoogleSheetsSourceConfig(spreadsheet_url="https://docs.google.com/spreadsheets/d/fake")

        with pytest.raises(PermissionError) as exc_info:
            get_schemas(config)

        assert "Spreadsheet access denied" in str(exc_info.value)


def test_get_worksheet_reraises_permission_error_with_message():
    with (
        mock.patch(
            "posthog.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
        ) as mock_google_sheets_client,
    ):
        instance = mock_google_sheets_client.return_value
        instance.open_by_url.side_effect = PermissionError()

        with pytest.raises(PermissionError) as exc_info:
            # Use a unique url/id to avoid the module-level TTLCache returning a prior result
            _get_worksheet("permission-error-url", 999)

        assert "Spreadsheet access denied" in str(exc_info.value)


def test_permission_error_is_non_retryable():
    """The message we re-raise from gspread's bare PermissionError must be a
    substring match for one of the source's non-retryable error keys, otherwise
    we'd retry a 403 forever."""
    source = GoogleSheetsSource()
    non_retryable_errors = source.get_non_retryable_errors()

    raised = PermissionError(
        "Spreadsheet access denied. Please share the spreadsheet with the PostHog service account."
    )
    error_msg = str(raised)

    assert any(key in error_msg for key in non_retryable_errors)
