from collections.abc import Callable
from typing import Any, Optional, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from posthog.temporal.data_imports.sources.notion.notion import (
    MAX_BLOCK_DEPTH,
    MAX_CHILD_PAGES_PER_PARENT,
    NOTION_VERSION,
    NotionResumeConfig,
    _get_headers,
    _iter_block_children,
    _search_body,
    _search_stream,
    validate_credentials,
)
from posthog.temporal.data_imports.sources.notion.settings import NOTION_ENDPOINTS

MODULE = "posthog.temporal.data_imports.sources.notion.notion"


class FakeResponse:
    def __init__(self, json_data: Any, status_code: int = 200, headers: Optional[dict[str, str]] = None) -> None:
        self._json = json_data
        self.status_code = status_code
        self.headers = headers or {}
        self.ok = 200 <= status_code < 400
        self.text = ""

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=cast(requests.Response, self))


class FakeSession:
    def __init__(self, responses: list[FakeResponse] | Callable[[int], FakeResponse]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def _next(self) -> FakeResponse:
        index = len(self.calls) - 1
        if callable(self._responses):
            return self._responses(index)
        return self._responses.pop(0)

    def request(
        self,
        method: str,
        url: str,
        json: Any = None,
        params: Any = None,
        timeout: Any = None,
    ) -> FakeResponse:
        self.calls.append({"method": method, "url": url, "json": json, "params": params})
        return self._next()

    def get(self, url: str, timeout: Any = None) -> FakeResponse:
        self.calls.append({"method": "GET", "url": url})
        return self._next()


def _list_response(results: list[dict[str, Any]], has_more: bool, next_cursor: str | None) -> FakeResponse:
    return FakeResponse({"results": results, "has_more": has_more, "next_cursor": next_cursor})


def _patch_session(session: FakeSession) -> Any:
    return mock.patch(f"{MODULE}.make_tracked_session", return_value=session)


class TestNotion:
    def test_headers_include_bearer_token_and_version(self) -> None:
        headers = _get_headers("ntn_secret")
        assert headers["Authorization"] == "Bearer ntn_secret"
        assert headers["Notion-Version"] == NOTION_VERSION
        assert headers["Content-Type"] == "application/json"

    @parameterized.expand([("page",), ("database",)])
    def test_search_body_shape(self, object_filter: str) -> None:
        body = _search_body(object_filter, None)
        assert body["filter"] == {"property": "object", "value": object_filter}
        assert body["sort"] == {"timestamp": "last_edited_time", "direction": "ascending"}
        assert body["page_size"] == 100
        assert "start_cursor" not in body

    def test_search_body_includes_cursor_when_set(self) -> None:
        body = _search_body("page", "cursor-123")
        assert body["start_cursor"] == "cursor-123"

    def test_search_stream_paginates_and_terminates(self) -> None:
        session = FakeSession(
            [
                _list_response([{"id": "p1"}], has_more=True, next_cursor="c1"),
                _list_response([{"id": "p2"}], has_more=False, next_cursor=None),
            ]
        )
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        with _patch_session(session):
            tables = list(_search_stream("tok", NOTION_ENDPOINTS["pages"], mock.MagicMock(), manager))

        total_rows = sum(t.num_rows for t in tables)
        assert total_rows == 2
        # Two pages fetched, then the loop terminates on has_more=False.
        assert len(session.calls) == 2

    def test_search_stream_resumes_from_saved_cursor(self) -> None:
        session = FakeSession([_list_response([{"id": "p1"}], has_more=False, next_cursor=None)])
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = NotionResumeConfig(next_cursor="resume-cursor")

        with _patch_session(session):
            list(_search_stream("tok", NOTION_ENDPOINTS["pages"], mock.MagicMock(), manager))

        # The first request must start from the persisted cursor.
        assert session.calls[0]["json"]["start_cursor"] == "resume-cursor"

    def test_block_children_inject_page_id(self) -> None:
        session = FakeSession([_list_response([{"id": "b1", "has_children": False}], has_more=False, next_cursor=None)])
        with _patch_session(session):
            blocks = list(_iter_block_children("tok", "block-root", "page-42", mock.MagicMock(), 0))

        assert len(blocks) == 1
        assert blocks[0]["_page_id"] == "page-42"

    def test_block_children_respect_depth_limit(self) -> None:
        # Every fetched block has children, so recursion would be unbounded without the depth cap.
        def always_has_children(_index: int) -> FakeResponse:
            return _list_response([{"id": "child", "has_children": True}], has_more=False, next_cursor=None)

        session = FakeSession(always_has_children)
        with _patch_session(session):
            blocks = list(_iter_block_children("tok", "block-root", "page-1", mock.MagicMock(), 0))

        # depth 0 yields one block, then recurses up to MAX_BLOCK_DEPTH levels.
        assert len(blocks) == MAX_BLOCK_DEPTH + 1

    def test_block_children_respect_page_cap(self) -> None:
        # Endpoint always reports another page; the per-parent cap must stop the scan.
        def always_more(_index: int) -> FakeResponse:
            return _list_response([{"id": "b", "has_children": False}], has_more=True, next_cursor="next")

        session = FakeSession(always_more)
        logger = mock.MagicMock()
        with _patch_session(session):
            blocks = list(_iter_block_children("tok", "block-root", "page-1", logger, 0))

        assert len(blocks) == MAX_CHILD_PAGES_PER_PARENT
        assert logger.warning.called

    @parameterized.expand([(200, True), (401, False), (403, False), (500, False)])
    def test_validate_credentials_status_mapping(self, status_code: int, expected_valid: bool) -> None:
        session = FakeSession([FakeResponse({}, status_code=status_code)])
        with _patch_session(session):
            valid, message = validate_credentials("tok")

        assert valid is expected_valid
        if expected_valid:
            assert message is None
        else:
            assert message is not None

    def test_validate_credentials_handles_exception(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session", side_effect=requests.ConnectionError("boom")):
            valid, message = validate_credentials("tok")

        assert valid is False
        assert message == "boom"


@pytest.mark.parametrize("endpoint", list(NOTION_ENDPOINTS.keys()))
def test_every_endpoint_has_config(endpoint: str) -> None:
    config = NOTION_ENDPOINTS[endpoint]
    assert config.name == endpoint
    assert config.stream_type in ("search", "users", "blocks", "comments")
    if config.stream_type == "search":
        assert config.object_filter in ("page", "database")
