import json
from typing import Any

import pytest
from unittest import mock

from requests import Request, Response

from posthog.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    JSONResponsePaginator,
    SinglePagePaginator,
)
from posthog.temporal.data_imports.sources.intercom import intercom as intercom_module
from posthog.temporal.data_imports.sources.intercom.intercom import (
    INTERCOM_API_BASE,
    IntercomSearchPaginator,
    _build_paginator,
    _build_search_body,
    _company_segments_generator,
    _conversation_parts_generator,
    _iter_companies,
    get_resource,
    intercom_source,
    validate_credentials,
)
from posthog.temporal.data_imports.sources.intercom.settings import INTERCOM_ENDPOINTS


def _make_response(json_body: Any, status_code: int = 200, text: str = "") -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(json_body).encode() if json_body is not None else text.encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,schema_name,expected_valid",
        [
            (200, None, True),
            (200, "contacts", True),
            (401, None, False),
            (401, "contacts", False),
            # 403 at source-create is accepted (token genuine, scope may be granted per-endpoint later)
            (403, None, True),
            # 403 for a specific schema means the scope is genuinely missing
            (403, "contacts", False),
            (500, None, False),
        ],
    )
    def test_status_mapping(self, status_code: int, schema_name: str | None, expected_valid: bool):
        mock_session = mock.MagicMock()
        mock_session.get.return_value = _make_response({"type": "admin"}, status_code=status_code, text="boom")

        with mock.patch.object(intercom_module, "make_tracked_session", return_value=mock_session):
            is_valid, error = validate_credentials("token", schema_name=schema_name)

        assert is_valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    def test_missing_token(self):
        is_valid, error = validate_credentials("")
        assert is_valid is False
        assert error is not None and "Missing" in error

    def test_request_exception_returns_invalid(self):
        mock_session = mock.MagicMock()
        mock_session.get.side_effect = Exception("connection reset")

        with mock.patch.object(intercom_module, "make_tracked_session", return_value=mock_session):
            is_valid, error = validate_credentials("token")

        assert is_valid is False
        assert error is not None and "connection reset" in error


class TestSearchPaginator:
    def test_update_state_sets_next_cursor(self):
        paginator = IntercomSearchPaginator()
        response = _make_response({"pages": {"next": {"starting_after": "cursor-123"}}})

        paginator.update_state(response)

        assert paginator.has_next_page is True
        assert paginator._next_cursor == "cursor-123"

    def test_update_state_terminal_when_no_next(self):
        paginator = IntercomSearchPaginator()
        response = _make_response({"pages": {"next": None}})

        paginator.update_state(response)

        assert paginator.has_next_page is False
        assert paginator._next_cursor is None

    def test_update_state_handles_bad_json(self):
        paginator = IntercomSearchPaginator()
        response = _make_response(None, text="not json")

        paginator.update_state(response)

        assert paginator.has_next_page is False

    def test_update_request_writes_cursor_into_body(self):
        paginator = IntercomSearchPaginator()
        paginator.update_state(_make_response({"pages": {"next": {"starting_after": "cursor-xyz"}}}))

        request = Request(method="POST", url=f"{INTERCOM_API_BASE}/contacts/search", json={"pagination": {}})
        paginator.update_request(request)

        assert request.json["pagination"]["starting_after"] == "cursor-xyz"

    def test_update_request_noop_without_cursor(self):
        paginator = IntercomSearchPaginator()
        request = Request(method="POST", url="http://x", json={"pagination": {}})

        paginator.update_request(request)

        assert "starting_after" not in request.json["pagination"]


class TestBuildSearchBody:
    def test_full_refresh_matches_all_records(self):
        body = _build_search_body(INTERCOM_ENDPOINTS["contacts"], "updated_at", None)

        assert body["query"] == {"field": "updated_at", "operator": ">", "value": 0}
        assert body["sort"] == {"field": "updated_at", "order": "ascending"}
        assert body["pagination"]["per_page"] == INTERCOM_ENDPOINTS["contacts"].page_size

    def test_incremental_uses_last_value(self):
        body = _build_search_body(INTERCOM_ENDPOINTS["conversations"], "updated_at", "1700000000")

        assert body["query"]["value"] == 1700000000


class TestBuildPaginator:
    @pytest.mark.parametrize(
        "kind,expected_type",
        [
            ("search", IntercomSearchPaginator),
            ("cursor", JSONResponseCursorPaginator),
            ("next_url", JSONResponsePaginator),
            ("single", SinglePagePaginator),
        ],
    )
    def test_paginator_per_kind(self, kind: str, expected_type: type):
        cfg = mock.MagicMock()
        cfg.paginator_kind = kind
        assert isinstance(_build_paginator(cfg), expected_type)


class TestGetResource:
    def test_search_incremental_upserts(self):
        resource = get_resource(
            "contacts",
            should_use_incremental_field=True,
            incremental_field="updated_at",
            db_incremental_field_last_value="1700000000",
        )

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        endpoint = resource["endpoint"]
        assert endpoint["method"] == "POST"
        assert endpoint["json"]["query"]["value"] == 1700000000

    def test_search_full_refresh_replaces_but_keeps_body(self):
        resource = get_resource(
            "contacts", should_use_incremental_field=False, incremental_field=None, db_incremental_field_last_value=None
        )

        assert resource["write_disposition"] == "replace"
        # Search endpoints always need a query body; value 0 matches everything.
        assert resource["endpoint"]["json"]["query"]["value"] == 0

    def test_post_list_endpoint_sets_per_page_body(self):
        resource = get_resource(
            "companies",
            should_use_incremental_field=False,
            incremental_field=None,
            db_incremental_field_last_value=None,
        )

        assert resource["endpoint"]["method"] == "POST"
        assert resource["endpoint"]["json"] == {"per_page": INTERCOM_ENDPOINTS["companies"].page_size}
        assert resource["write_disposition"] == "replace"

    def test_query_param_incremental_sets_cursor(self):
        resource = get_resource(
            "activity_logs",
            should_use_incremental_field=True,
            incremental_field="created_at",
            db_incremental_field_last_value="1700000000",
        )

        assert resource["endpoint"]["params"]["created_at_after"] == 1700000000
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    def test_query_param_full_refresh_uses_epoch(self):
        resource = get_resource(
            "activity_logs",
            should_use_incremental_field=False,
            incremental_field=None,
            db_incremental_field_last_value=None,
        )

        assert resource["endpoint"]["params"]["created_at_after"] == 0
        assert resource["write_disposition"] == "replace"

    def test_single_endpoint_with_extra_params(self):
        resource = get_resource(
            "company_attributes",
            should_use_incremental_field=False,
            incremental_field=None,
            db_incremental_field_last_value=None,
        )

        assert resource["endpoint"]["params"] == {"model": "company"}

    def test_single_endpoint_without_params(self):
        resource = get_resource(
            "admins", should_use_incremental_field=False, incremental_field=None, db_incremental_field_last_value=None
        )

        assert "params" not in resource["endpoint"]

    @pytest.mark.parametrize("name", list(INTERCOM_ENDPOINTS.keys()))
    def test_table_format_and_name(self, name: str):
        # Substream endpoints are not routed through get_resource.
        if INTERCOM_ENDPOINTS[name].paginator_kind == "substream":
            return
        resource = get_resource(
            name, should_use_incremental_field=False, incremental_field=None, db_incremental_field_last_value=None
        )
        assert resource["name"] == name
        assert resource["table_name"] == name
        assert resource["table_format"] == "delta"


class TestSubstreamGenerators:
    def test_conversation_parts_injects_conversation_id(self):
        mock_session = mock.MagicMock()
        mock_session.post.side_effect = [
            _make_response({"conversations": [{"id": "c1"}, {"id": "c2"}], "pages": {}}),
        ]
        mock_session.get.side_effect = [
            _make_response({"conversation_parts": {"conversation_parts": [{"id": "p1"}, {"id": "p2"}]}}),
            _make_response({"conversation_parts": {"conversation_parts": [{"id": "p3"}]}}),
        ]

        parts = list(_conversation_parts_generator(mock_session, "updated_at", None))

        assert [p["id"] for p in parts] == ["p1", "p2", "p3"]
        assert {p["conversation_id"] for p in parts} == {"c1", "c2"}

    def test_company_segments_injects_company_id(self):
        mock_session = mock.MagicMock()
        mock_session.post.side_effect = [
            _make_response({"data": [{"id": "co1"}, {"id": "co2"}], "pages": {}}),
        ]
        mock_session.get.side_effect = [
            _make_response({"data": [{"id": "s1"}]}),
            _make_response({"data": [{"id": "s2"}, {"id": "s3"}]}),
        ]

        segments = list(_company_segments_generator(mock_session))

        assert [s["id"] for s in segments] == ["s1", "s2", "s3"]
        assert segments[0]["company_id"] == "co1"
        assert segments[1]["company_id"] == "co2"

    def test_iter_companies_follows_next_url(self):
        next_url = f"{INTERCOM_API_BASE}/companies/list?cursor=2"
        mock_session = mock.MagicMock()
        mock_session.post.side_effect = [
            _make_response({"data": [{"id": "co1"}], "pages": {"next": next_url}}),
        ]
        mock_session.get.side_effect = [
            _make_response({"data": [{"id": "co2"}], "pages": {}}),
        ]

        companies = list(_iter_companies(mock_session))

        assert [c["id"] for c in companies] == ["co1", "co2"]
        assert mock_session.get.call_args_list[0].args[0] == next_url


class TestIntercomSource:
    @pytest.mark.parametrize("endpoint", list(INTERCOM_ENDPOINTS.keys()))
    def test_source_response_metadata(self, endpoint: str):
        cfg = INTERCOM_ENDPOINTS[endpoint]
        sentinel = object()

        with (
            mock.patch.object(intercom_module, "rest_api_resource", return_value=sentinel),
            mock.patch.object(intercom_module, "make_tracked_session", return_value=mock.MagicMock()),
        ):
            response = intercom_source(
                access_token="token",
                endpoint=endpoint,
                team_id=1,
                job_id="job-1",
            )

        assert response.name == endpoint
        assert response.primary_keys == cfg.primary_keys
        assert response.partition_keys == [cfg.partition_key]
        assert response.sort_mode == cfg.sort_mode
