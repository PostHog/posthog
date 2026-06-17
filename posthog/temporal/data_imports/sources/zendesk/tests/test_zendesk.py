import json
from typing import Any

import pytest

from requests import Request, Response

from posthog.temporal.data_imports.sources.zendesk.zendesk import (
    ZendeskTicketsCursorIncrementalPaginator,
    normalize_subdomain,
)


def _make_response(json_body: dict[str, Any] | None = None) -> Response:
    resp = Response()
    resp.status_code = 200
    resp.headers["Content-Type"] = "application/json"
    resp._content = json.dumps(json_body or {}).encode()
    return resp


class TestNormalizeSubdomain:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            pytest.param("nibbles", "nibbles", id="bare_subdomain"),
            pytest.param("nibbles.zendesk.com", "nibbles", id="full_host"),
            pytest.param("https://nibbles.zendesk.com", "nibbles", id="https_url"),
            pytest.param("https://nibbles.zendesk.com/", "nibbles", id="https_url_trailing_slash"),
            pytest.param("http://nibbles.zendesk.com/api/v2", "nibbles", id="url_with_path"),
            pytest.param("  nibbles.zendesk.com  ", "nibbles", id="whitespace"),
            pytest.param("nibbles.ZENDESK.com", "nibbles", id="mixed_case_host"),
            pytest.param("multi-word-team", "multi-word-team", id="hyphenated_subdomain"),
        ],
    )
    def test_collapses_to_subdomain_label(self, raw: str, expected: str) -> None:
        assert normalize_subdomain(raw) == expected

    def test_full_host_does_not_double_when_building_base_url(self) -> None:
        # Regression: a pasted full host previously produced "nibbles.zendesk.com.zendesk.com",
        # whose TLS handshake the Zendesk edge rejects.
        assert f"https://{normalize_subdomain('nibbles.zendesk.com')}.zendesk.com/" == "https://nibbles.zendesk.com/"


class TestZendeskTicketsCursorIncrementalPaginator:
    def test_advances_to_next_cursor(self) -> None:
        p = ZendeskTicketsCursorIncrementalPaginator()
        resp = _make_response({"tickets": [{"id": 1}], "after_cursor": "abc123", "end_of_stream": False})

        p.update_state(resp)

        assert p.has_next_page is True

        req = Request(method="GET", url="https://x.zendesk.com/api/v2/incremental/tickets/cursor")
        req.params = {"per_page": 1000, "start_time": 1591394586}
        p.update_request(req)

        assert req.params["cursor"] == "abc123"
        # The seed start_time is dropped once we paginate by cursor.
        assert "start_time" not in req.params
        assert req.params["per_page"] == 1000

    def test_first_request_keeps_seed_start_time(self) -> None:
        p = ZendeskTicketsCursorIncrementalPaginator()

        # Before any response, has_next_page is True and no cursor is set, so the
        # first request must go out untouched (with its seed start_time).
        assert p.has_next_page is True

        req = Request(method="GET", url="https://x.zendesk.com/api/v2/incremental/tickets/cursor")
        req.params = {"per_page": 1000, "start_time": 1591394586}
        p.init_request(req)

        assert req.params["start_time"] == 1591394586
        assert "cursor" not in req.params

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"tickets": [], "after_cursor": "abc123", "end_of_stream": True}, id="end_of_stream"),
            pytest.param({}, id="empty_response"),
        ],
    )
    def test_stops_pagination(self, body: dict[str, Any]) -> None:
        p = ZendeskTicketsCursorIncrementalPaginator()

        p.update_state(_make_response(body))

        assert p.has_next_page is False

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"tickets": [{"id": 1}], "after_cursor": None, "end_of_stream": False}, id="missing_cursor"),
            pytest.param({"tickets": [{"id": 1}], "after_cursor": "abc123"}, id="missing_end_of_stream"),
        ],
    )
    def test_raises_on_invalid_response(self, body: dict[str, Any]) -> None:
        p = ZendeskTicketsCursorIncrementalPaginator()

        with pytest.raises(ValueError):
            p.update_state(_make_response(body))

    def test_raises_when_cursor_does_not_advance(self) -> None:
        """A cursor that never moves while end_of_stream is False is the time-based
        export's failure mode; fail loud so the activity retries instead of
        silently truncating data."""
        p = ZendeskTicketsCursorIncrementalPaginator()

        first = _make_response({"tickets": [{"id": 1}], "after_cursor": "abc123", "end_of_stream": False})
        p.update_state(first)
        assert p.has_next_page is True

        repeated = _make_response({"tickets": [{"id": 1}], "after_cursor": "abc123", "end_of_stream": False})
        with pytest.raises(ValueError):
            p.update_state(repeated)

    def test_paginates_across_multiple_pages(self) -> None:
        p = ZendeskTicketsCursorIncrementalPaginator()
        req = Request(method="GET", url="https://x.zendesk.com/api/v2/incremental/tickets/cursor")
        req.params = {"per_page": 1000, "start_time": 1591394586}

        p.update_state(_make_response({"tickets": [{"id": 1}], "after_cursor": "cursor_1", "end_of_stream": False}))
        p.update_request(req)
        assert req.params["cursor"] == "cursor_1"

        p.update_state(_make_response({"tickets": [{"id": 2}], "after_cursor": "cursor_2", "end_of_stream": False}))
        p.update_request(req)
        assert req.params["cursor"] == "cursor_2"

        p.update_state(_make_response({"tickets": [{"id": 3}], "after_cursor": "cursor_3", "end_of_stream": True}))
        assert p.has_next_page is False
