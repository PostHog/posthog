from typing import Any

import pytest
from unittest import mock

from posthog.temporal.data_imports.sources.intercom.intercom import (
    IntercomCursorPaginator,
    get_resource,
    validate_credentials,
)


class TestIntercomCursorPaginator:
    def test_has_next_page_with_cursor(self):
        paginator = IntercomCursorPaginator()
        response = mock.MagicMock()
        response.json.return_value = {
            "data": [{"id": "1"}],
            "pages": {"next": {"starting_after": "abc123"}},
        }

        paginator.update_state(response)

        assert paginator.has_next_page is True

    def test_no_next_page_without_cursor(self):
        paginator = IntercomCursorPaginator()
        response = mock.MagicMock()
        response.json.return_value = {
            "data": [{"id": "1"}],
            "pages": {"next": None},
        }

        paginator.update_state(response)

        assert paginator.has_next_page is False

    def test_no_next_page_empty_response(self):
        paginator = IntercomCursorPaginator()
        response = mock.MagicMock()
        response.json.return_value = {}

        paginator.update_state(response)

        assert paginator.has_next_page is False

    def test_update_request_sets_starting_after(self):
        paginator = IntercomCursorPaginator()
        response = mock.MagicMock()
        response.json.return_value = {
            "data": [{"id": "1"}],
            "pages": {"next": {"starting_after": "cursor_value"}},
        }
        paginator.update_state(response)

        request = mock.MagicMock()
        request.params = {}
        paginator.update_request(request)

        assert request.params["starting_after"] == "cursor_value"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_valid",
        [
            (200, True),
            (401, False),
        ],
    )
    def test_validate_credentials(self, status_code, expected_valid):
        with mock.patch("posthog.temporal.data_imports.sources.intercom.intercom.requests.get") as mock_get:
            mock_response = mock.MagicMock()
            mock_response.status_code = status_code
            mock_response.json.return_value = {"errors": [{"message": "Unauthorized"}]}
            mock_response.text = "Unauthorized"
            mock_get.return_value = mock_response

            is_valid, error = validate_credentials("test_key")

            assert is_valid is expected_valid
            mock_get.assert_called_once()

    def test_validate_credentials_request_exception(self):
        with mock.patch("posthog.temporal.data_imports.sources.intercom.intercom.requests.get") as mock_get:
            from requests.exceptions import ConnectionError

            mock_get.side_effect = ConnectionError("Connection failed")

            is_valid, error = validate_credentials("test_key")

            assert is_valid is False
            assert error is not None and "Connection failed" in error


class TestGetResource:
    @pytest.mark.parametrize(
        "endpoint_name,expected_data_selector,expected_path",
        [
            ("contacts", "data", "/contacts"),
            ("conversations", "conversations", "/conversations"),
            ("admins", "admins", "/admins"),
            ("tags", "data", "/tags"),
            ("teams", "teams", "/teams"),
            ("data_attributes", "data", "/data_attributes"),
        ],
    )
    def test_get_resource_returns_correct_config(self, endpoint_name, expected_data_selector, expected_path):
        resource = get_resource(endpoint_name, should_use_incremental_field=False)

        assert resource["name"] == endpoint_name
        assert resource["table_name"] == endpoint_name
        assert resource["primary_key"] == "id"
        assert resource["write_disposition"] == "replace"
        endpoint: dict[str, Any] = resource["endpoint"]  # type: ignore[assignment]
        assert endpoint["data_selector"] == expected_data_selector
        assert endpoint["path"] == expected_path

    def test_get_resource_with_incremental_uses_merge(self):
        resource = get_resource("contacts", should_use_incremental_field=True)

        assert resource["write_disposition"] == {
            "disposition": "merge",
            "strategy": "upsert",
        }
