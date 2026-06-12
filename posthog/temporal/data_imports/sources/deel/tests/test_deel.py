from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from posthog.temporal.data_imports.sources.deel.deel import (
    PAGE_SIZE,
    DeelResumeConfig,
    deel_source,
    get_rows,
    validate_credentials,
)
from posthog.temporal.data_imports.sources.deel.settings import DEEL_ENDPOINTS, ENDPOINTS


def _make_manager(resume_state: DeelResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(items: list[dict[str, Any]], cursor: str | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    body: dict[str, Any] = {"data": items, "page": {"total_rows": len(items)}}
    if cursor is not None:
        body["page"]["cursor"] = cursor
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


@pytest.fixture(autouse=True)
def _no_sleep():
    with mock.patch("posthog.temporal.data_imports.sources.deel.deel.time.sleep"):
        yield


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            # A valid token without people:read still 403s; only 401 means the
            # token itself is bad.
            (403, True),
            (401, False),
        ],
    )
    @mock.patch("posthog.temporal.data_imports.sources.deel.deel.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("token") is expected

    @mock.patch("posthog.temporal.data_imports.sources.deel.deel.make_tracked_session")
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False


class TestGetRowsOffsetPagination:
    @mock.patch("posthog.temporal.data_imports.sources.deel.deel.make_tracked_session")
    def test_paginates_until_short_page(self, mock_session):
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        mock_session.return_value.get.side_effect = [
            _response(full_page),
            _response([{"id": "last"}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "people", mock.MagicMock(), manager))

        assert len(batches) == 2
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].offset == PAGE_SIZE
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(second_url).query)["offset"] == [str(PAGE_SIZE)]

    @mock.patch("posthog.temporal.data_imports.sources.deel.deel.make_tracked_session")
    def test_resumes_from_saved_offset(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager(DeelResumeConfig(offset=150))
        list(get_rows("token", "people", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["offset"] == ["150"]

    @mock.patch("posthog.temporal.data_imports.sources.deel.deel.make_tracked_session")
    def test_empty_response_stops_without_saving_state(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        batches = list(get_rows("token", "people", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()


class TestGetRowsCursorPagination:
    @mock.patch("posthog.temporal.data_imports.sources.deel.deel.make_tracked_session")
    def test_paginates_via_after_cursor(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "1"}], cursor="cur_abc"),
            _response([{"id": "2"}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "contracts", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["1", "2"]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].cursor == "cur_abc"
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(second_url).query)["after_cursor"] == ["cur_abc"]

    @mock.patch("posthog.temporal.data_imports.sources.deel.deel.make_tracked_session")
    def test_resumes_from_saved_cursor(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager(DeelResumeConfig(cursor="cur_resume"))
        list(get_rows("token", "contracts", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["after_cursor"] == ["cur_resume"]

    @mock.patch("posthog.temporal.data_imports.sources.deel.deel.make_tracked_session")
    def test_empty_page_with_cursor_stops(self, mock_session):
        mock_session.return_value.get.return_value = _response([], cursor="cur_loop")

        manager = _make_manager()
        batches = list(get_rows("token", "contracts", mock.MagicMock(), manager))

        assert batches == []
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()


class TestDeelSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = DEEL_ENDPOINTS[endpoint]
        response = deel_source("token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(DEEL_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "created_at"
