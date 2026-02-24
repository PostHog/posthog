from datetime import date, datetime

import pytest
from unittest.mock import MagicMock

from posthog.temporal.data_imports.sources.mailchimp.mailchimp import (
    MailchimpPaginator,
    _format_incremental_value,
    extract_data_center,
)


class TestExtractDataCenter:
    def test_basic_key(self):
        assert extract_data_center("abc123def456-us6") == "us6"

    def test_multiple_dashes(self):
        assert extract_data_center("abc-def-ghi-us10") == "us10"

    def test_invalid_key_raises(self):
        with pytest.raises(ValueError, match="Invalid Mailchimp API key format"):
            extract_data_center("invalidkey")


class TestFormatIncrementalValue:
    def test_datetime(self):
        dt = datetime(2024, 1, 15, 10, 30, 45)
        result = _format_incremental_value(dt)
        assert result == "2024-01-15T10:30:45+00:00"

    def test_date(self):
        d = date(2024, 1, 15)
        result = _format_incremental_value(d)
        assert result == "2024-01-15T00:00:00+00:00"

    def test_string(self):
        assert _format_incremental_value("2024-01-15") == "2024-01-15"


class TestMailchimpPaginator:
    def test_initial_state(self):
        paginator = MailchimpPaginator(page_size=100)
        assert paginator._page_size == 100
        assert paginator._offset == 0

    def test_update_state_has_more(self):
        paginator = MailchimpPaginator(page_size=100)
        response = MagicMock()
        response.json.return_value = {"total_items": 250, "lists": []}
        paginator.update_state(response)
        assert paginator._offset == 100
        assert paginator._has_next_page is True

    def test_update_state_no_more(self):
        paginator = MailchimpPaginator(page_size=100)
        paginator._offset = 200
        response = MagicMock()
        response.json.return_value = {"total_items": 250, "lists": []}
        paginator.update_state(response)
        assert paginator._offset == 300
        assert paginator._has_next_page is False
