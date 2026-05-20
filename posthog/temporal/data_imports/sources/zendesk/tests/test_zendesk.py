import json
from typing import Any

from requests import Request, Response

from posthog.temporal.data_imports.sources.zendesk.zendesk import ZendeskTicketsCursorIncrementalPaginator


def _make_response(json_body: dict[str, Any] | None = None) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(json_body or {}).encode()
    return resp


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

    def test_stops_on_end_of_stream(self) -> None:
        p = ZendeskTicketsCursorIncrementalPaginator()
        resp = _make_response({"tickets": [], "after_cursor": "abc123", "end_of_stream": True})

        p.update_state(resp)

        assert p.has_next_page is False

    def test_stops_when_after_cursor_missing(self) -> None:
        p = ZendeskTicketsCursorIncrementalPaginator()
        resp = _make_response({"tickets": [{"id": 1}], "after_cursor": None, "end_of_stream": False})

        p.update_state(resp)

        assert p.has_next_page is False

    def test_stops_when_response_empty(self) -> None:
        p = ZendeskTicketsCursorIncrementalPaginator()

        p.update_state(_make_response({}))

        assert p.has_next_page is False

    def test_stops_when_cursor_does_not_advance(self) -> None:
        """The time-based export's failure mode (a cursor that never moves) must
        terminate rather than loop forever re-fetching the same page."""
        p = ZendeskTicketsCursorIncrementalPaginator()

        first = _make_response({"tickets": [{"id": 1}], "after_cursor": "abc123", "end_of_stream": False})
        p.update_state(first)
        assert p.has_next_page is True

        repeated = _make_response({"tickets": [{"id": 1}], "after_cursor": "abc123", "end_of_stream": False})
        p.update_state(repeated)
        assert p.has_next_page is False

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
