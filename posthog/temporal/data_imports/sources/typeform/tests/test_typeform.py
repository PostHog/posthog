from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

import requests
from parameterized import parameterized

from posthog.temporal.data_imports.sources.typeform.typeform import (
    TypeformFormsPaginator,
    TypeformResponsesPaginator,
    _validated_api_base_url,
    get_resource,
    typeform_source,
    validate_credentials,
)


class _FakeDltResource:
    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


class TestTypeformTransport:
    @parameterized.expand([("has_next_page", 1, 3, True), ("last_page", 3, 3, False)])
    def test_forms_paginator_update_state(self, _name, current_page, page_count, expected_has_next) -> None:
        paginator = TypeformFormsPaginator()
        paginator._current_page = current_page
        response = Mock()
        response.json.return_value = {"page_count": page_count}

        paginator.update_state(response, data=[{"id": "abc"}])

        assert paginator.has_next_page == expected_has_next

    def test_forms_paginator_update_request_increments_page(self) -> None:
        paginator = TypeformFormsPaginator()
        request = Mock()
        request.params = {"page": 1}

        paginator.update_request(request)

        assert request.params["page"] == 2

    def test_responses_paginator_update_state_sets_cursor(self) -> None:
        paginator = TypeformResponsesPaginator()
        response = Mock()

        paginator.update_state(response, data=[{"token": "tok_1"}, {"token": "tok_2"}])

        assert paginator.has_next_page is True

    def test_responses_paginator_update_state_empty_data_stops(self) -> None:
        paginator = TypeformResponsesPaginator()
        response = Mock()

        paginator.update_state(response, data=[])

        assert paginator.has_next_page is False

    def test_responses_paginator_update_request_sets_before(self) -> None:
        paginator = TypeformResponsesPaginator()
        response = Mock()
        paginator.update_state(response, data=[{"token": "tok_1"}])

        request = Mock()
        request.params = {
            "page_size": 1000,
            "since": "2026-03-01T00:00:00Z",
            "until": "2026-03-25T00:00:00Z",
        }
        paginator.update_request(request)

        assert request.params["before"] == "tok_1"
        assert "since" not in request.params
        assert "until" not in request.params

    def test_validated_api_base_url_rejects_unknown(self) -> None:
        with pytest.raises(
            ValueError,
            match="API base URL must be one of https://api.typeform.com, https://api.eu.typeform.com, or https://api.typeform.eu.",
        ):
            _validated_api_base_url("https://invalid.typeform.com")

    @patch("posthog.temporal.data_imports.sources.typeform.typeform.requests.get")
    def test_validate_credentials_handles_request_exception(self, mock_get) -> None:
        mock_get.side_effect = requests.exceptions.RequestException("boom")
        result = validate_credentials(auth_token="token", api_base_url="https://api.typeform.com")
        assert result == (False, "/forms request failed: boom")

    @patch("posthog.temporal.data_imports.sources.typeform.typeform.requests.get")
    def test_validate_credentials_checks_forms_and_responses_endpoints(self, mock_get) -> None:
        forms_response = Mock(status_code=200, text="ok")
        forms_response.json.return_value = {"items": [{"id": "form_1"}]}
        responses_response = Mock(status_code=200, text="ok")
        responses_response.json.return_value = {"items": []}
        mock_get.side_effect = [forms_response, responses_response]

        result = validate_credentials(auth_token="token", api_base_url="https://api.typeform.com")

        assert result == (True, None)
        assert mock_get.call_count == 2
        assert mock_get.call_args_list[0].args[0] == "https://api.typeform.com/forms"
        assert mock_get.call_args_list[1].args[0] == "https://api.typeform.com/forms/form_1/responses"

    @patch("posthog.temporal.data_imports.sources.typeform.typeform.requests.get")
    def test_validate_credentials_returns_error_when_forms_endpoint_fails(self, mock_get) -> None:
        forms_response = Mock(status_code=403, text="forbidden")
        forms_response.json.return_value = {"description": "forbidden"}
        mock_get.side_effect = [forms_response]

        result = validate_credentials(auth_token="token", api_base_url="https://api.typeform.com")

        assert result == (False, "Typeform token is missing required scope for forms endpoint: forms:read")

    @patch("posthog.temporal.data_imports.sources.typeform.typeform.requests.get")
    def test_validate_credentials_returns_error_when_responses_endpoint_fails(self, mock_get) -> None:
        forms_response = Mock(status_code=200, text="ok")
        forms_response.json.return_value = {"items": [{"id": "form_1"}]}
        responses_response = Mock(status_code=403, text="forbidden")
        responses_response.json.return_value = {"description": "forbidden"}
        mock_get.side_effect = [forms_response, responses_response]

        result = validate_credentials(auth_token="token", api_base_url="https://api.typeform.com")

        assert result == (False, "Typeform token is missing required scope for responses endpoint: responses:read")

    @patch("posthog.temporal.data_imports.sources.typeform.typeform.requests.get")
    def test_validate_credentials_returns_success_when_no_forms_exist(self, mock_get) -> None:
        forms_response = Mock(status_code=200, text="ok")
        forms_response.json.return_value = {"items": []}
        mock_get.side_effect = [forms_response]

        result = validate_credentials(auth_token="token", api_base_url="https://api.typeform.com")

        assert result == (True, None)
        assert mock_get.call_count == 1

    @patch("posthog.temporal.data_imports.sources.typeform.typeform.requests.get")
    def test_validate_credentials_for_forms_schema_only_skips_responses_probe(self, mock_get) -> None:
        forms_response = Mock(status_code=200, text="ok")
        forms_response.json.return_value = {"items": [{"id": "form_1"}]}
        mock_get.side_effect = [forms_response]

        result = validate_credentials(
            auth_token="token",
            api_base_url="https://api.typeform.com",
            schema_name="forms",
        )

        assert result == (True, None)
        assert mock_get.call_count == 1
        assert mock_get.call_args_list[0].args[0] == "https://api.typeform.com/forms"

    @patch("posthog.temporal.data_imports.sources.typeform.typeform.requests.get")
    def test_validate_credentials_for_responses_schema_only_skips_me_probe(self, mock_get) -> None:
        forms_response = Mock(status_code=200, text="ok")
        forms_response.json.return_value = {"items": [{"id": "form_1"}]}
        responses_response = Mock(status_code=200, text="ok")
        responses_response.json.return_value = {"items": []}
        mock_get.side_effect = [forms_response, responses_response]

        result = validate_credentials(
            auth_token="token",
            api_base_url="https://api.typeform.com",
            schema_name="responses",
        )

        assert result == (True, None)
        assert mock_get.call_count == 2
        assert mock_get.call_args_list[0].args[0] == "https://api.typeform.com/forms"
        assert mock_get.call_args_list[1].args[0] == "https://api.typeform.com/forms/form_1/responses"

    def test_get_resource_forms_non_incremental(self) -> None:
        resource = cast(
            dict[str, Any],
            get_resource(
                endpoint="forms",
                should_use_incremental_field=False,
            ),
        )
        assert resource["name"] == "forms"
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["path"] == "/forms"
        assert resource["endpoint"]["data_selector"] == "items"
        assert resource["endpoint"]["params"]["page_size"] == 200
        assert resource["primary_key"] == "id"
        assert resource["table_format"] == "delta"

    def test_get_resource_forms_incremental(self) -> None:
        resource = cast(
            dict[str, Any],
            get_resource(
                endpoint="forms",
                should_use_incremental_field=True,
                incremental_field="last_updated_at",
            ),
        )
        assert resource["write_disposition"]["disposition"] == "merge"
        assert resource["endpoint"]["incremental"]["start_param"] == "since"
        assert resource["endpoint"]["incremental"]["end_param"] == "until"
        assert resource["endpoint"]["incremental"]["cursor_path"] == "last_updated_at"

    def test_get_resource_rejects_responses_fanout(self) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource(endpoint="responses", should_use_incremental_field=False)

    @patch("posthog.temporal.data_imports.sources.typeform.typeform.rest_api_resources")
    def test_typeform_source_forms_response(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [Mock()]
        response = typeform_source(
            auth_token="token",
            api_base_url="https://api.typeform.com",
            endpoint="forms",
            team_id=1,
            job_id="job-1",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 1, tzinfo=UTC),
            incremental_field="last_updated_at",
        )

        assert response.name == "forms"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"

    @patch("posthog.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources")
    def test_typeform_source_responses_fanout_row_format(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("forms", [{"id": "form_1"}]),
            _FakeDltResource("responses", [{"response_id": "resp_1", "_forms_id": "form_1"}]),
        ]

        response = typeform_source(
            auth_token="token",
            api_base_url="https://api.typeform.com",
            endpoint="responses",
            team_id=1,
            job_id="job-1",
        )
        rows = list(cast(Any, response.items()))
        assert rows == [{"response_id": "resp_1", "form_id": "form_1"}]
        assert response.partition_mode == "datetime"

    @patch("posthog.temporal.data_imports.sources.typeform.typeform.build_dependent_resource")
    def test_typeform_source_responses_passes_items_data_selector_to_fanout(
        self, mock_build_dependent_resource
    ) -> None:
        mock_build_dependent_resource.return_value = iter([])

        typeform_source(
            auth_token="token",
            api_base_url="https://api.typeform.com",
            endpoint="responses",
            team_id=1,
            job_id="job-1",
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["page_size_param"] == "page_size"
        assert kwargs["parent_endpoint_extra"]["data_selector"] == "items"
        assert kwargs["child_endpoint_extra"]["data_selector"] == "items"
        assert isinstance(kwargs["parent_endpoint_extra"]["paginator"], TypeformFormsPaginator)
        assert isinstance(kwargs["child_endpoint_extra"]["paginator"], TypeformResponsesPaginator)

    def test_typeform_source_rejects_unknown_api_base_url(self) -> None:
        with pytest.raises(
            ValueError,
            match="API base URL must be one of https://api.typeform.com, https://api.eu.typeform.com, or https://api.typeform.eu.",
        ):
            typeform_source(
                auth_token="token",
                api_base_url="https://invalid.typeform.com",
                endpoint="forms",
                team_id=1,
                job_id="job-1",
            )
