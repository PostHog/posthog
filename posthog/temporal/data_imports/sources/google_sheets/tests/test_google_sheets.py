from unittest import mock

import gspread
import pytest
from posthog.temporal.data_imports.sources.google_sheets.google_sheets import _get_worksheet


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
