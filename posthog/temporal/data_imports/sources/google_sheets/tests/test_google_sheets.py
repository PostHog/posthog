import pytest
from unittest import mock

import gspread

from posthog.temporal.data_imports.sources.generated_configs import GoogleSheetsSourceConfig
from posthog.temporal.data_imports.sources.google_sheets.google_sheets import (
    _PERMISSION_DENIED_MESSAGE,
    _get_worksheet,
    get_schemas,
)
from posthog.temporal.data_imports.sources.google_sheets.source import GoogleSheetsSource
from posthog.temporal.data_imports.util import NonRetryableException


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
def test_reraises_permission_error_as_non_retryable(call_site):
    with mock.patch(
        "posthog.temporal.data_imports.sources.google_sheets.google_sheets.google_sheets_client"
    ) as mock_google_sheets_client:
        instance = mock_google_sheets_client.return_value
        instance.open_by_url.side_effect = PermissionError()

        with pytest.raises(NonRetryableException) as exc_info:
            call_site()

        # The descriptive message lives on the chained `PermissionError` (not on
        # `NonRetryableException` itself) so that `update_external_data_job_model`,
        # which inspects `str(e.cause.cause)` for `NonRetryableException` activity
        # failures, still sees the message and can map it to a friendly error.
        cause = exc_info.value.__cause__
        assert isinstance(cause, PermissionError)
        assert str(cause) == _PERMISSION_DENIED_MESSAGE
        assert "Spreadsheet access denied" in str(cause)


def test_permission_error_message_matches_non_retryable_key():
    source = GoogleSheetsSource()
    non_retryable_errors = source.get_non_retryable_errors()

    chained = PermissionError(_PERMISSION_DENIED_MESSAGE)
    error_msg = str(chained)

    assert any(key in error_msg for key in non_retryable_errors)
