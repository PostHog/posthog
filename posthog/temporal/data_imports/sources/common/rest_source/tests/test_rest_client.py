import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from posthog.temporal.data_imports.sources.common.rest_source.exceptions import IgnoreResponseException
from posthog.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator, SinglePagePaginator
from posthog.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient, RESTClientRetryableError


def _make_response(json_body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(json_body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestRESTClient:
    @patch("posthog.temporal.data_imports.sources.common.rest_source.rest_client.requests.Session")
    def test_paginate_single_page(self, MockSession) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()
        mock_session.send.return_value = _make_response({"results": [{"id": 1}, {"id": 2}]})

        client = RESTClient(base_url="https://api.example.com")
        pages = list(client.paginate(path="/items", data_selector="results", paginator=SinglePagePaginator()))

        assert len(pages) == 1
        assert pages[0] == [{"id": 1}, {"id": 2}]

    @patch("posthog.temporal.data_imports.sources.common.rest_source.rest_client.requests.Session")
    def test_paginate_multiple_pages(self, MockSession) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()

        responses = [
            _make_response([{"id": 1}]),
            _make_response([{"id": 2}]),
        ]
        mock_session.send.side_effect = responses

        class TwoPagePaginator(BasePaginator):
            def __init__(self):
                super().__init__()
                self._page = 0

            def update_state(self, response, data=None):
                self._page += 1
                self._has_next_page = self._page < 2

            def update_request(self, request):
                pass

        client = RESTClient(base_url="https://api.example.com")
        pages = list(client.paginate(path="/items", paginator=TwoPagePaginator()))

        assert len(pages) == 2
        assert pages[0] == [{"id": 1}]
        assert pages[1] == [{"id": 2}]

    @patch("posthog.temporal.data_imports.sources.common.rest_source.rest_client.requests.Session")
    def test_paginate_with_hooks(self, MockSession) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()
        mock_session.send.return_value = _make_response({"data": [{"id": 1}]})

        hook_called = []

        def my_hook(response, **kwargs):
            hook_called.append(True)

        client = RESTClient(base_url="https://api.example.com")
        list(
            client.paginate(
                path="/items",
                data_selector="data",
                paginator=SinglePagePaginator(),
                hooks={"response": [my_hook]},
            )
        )

        assert len(hook_called) == 1

    @patch("posthog.temporal.data_imports.sources.common.rest_source.rest_client.requests.Session")
    def test_paginate_ignore_response_breaks_loop(self, MockSession) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()

        def raise_ignore(response, **kwargs):
            raise IgnoreResponseException()

        mock_session.send.return_value = _make_response({"data": []})

        client = RESTClient(base_url="https://api.example.com")
        pages = list(
            client.paginate(
                path="/items",
                paginator=SinglePagePaginator(),
                hooks={"response": [raise_ignore]},
            )
        )

        assert len(pages) == 0

    def test_join_url(self) -> None:
        client = RESTClient(base_url="https://api.example.com")
        assert client._join_url("/items") == "https://api.example.com/items"
        assert client._join_url("items") == "https://api.example.com/items"

    def test_join_url_absolute_path(self) -> None:
        client = RESTClient(base_url="https://api.example.com")
        assert client._join_url("https://other.com/items") == "https://other.com/items"

    @patch("posthog.temporal.data_imports.sources.common.rest_source.rest_client.requests.Session")
    def test_paginate_invokes_resume_hook_after_each_page(self, MockSession) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()

        responses = [
            _make_response([{"id": 1}]),
            _make_response([{"id": 2}]),
        ]
        mock_session.send.side_effect = responses

        class TwoPagePaginator(BasePaginator):
            def __init__(self):
                super().__init__()
                self._page = 0

            def update_state(self, response, data=None):
                self._page += 1
                self._has_next_page = self._page < 2

            def update_request(self, request):
                pass

            def get_resume_state(self):
                return {"page": self._page}

        saved: list[Any] = []

        client = RESTClient(base_url="https://api.example.com")
        list(client.paginate(path="/items", paginator=TwoPagePaginator(), resume_hook=saved.append))

        # Called once between page 1 and page 2 with the next-page state, and
        # once on the terminal page with None (no more pages to resume to).
        assert saved == [{"page": 1}, None]

    @patch("posthog.temporal.data_imports.sources.common.rest_source.rest_client.requests.Session")
    def test_paginate_seeds_initial_paginator_state(self, MockSession) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()
        mock_session.send.return_value = _make_response([{"id": 99}])

        class ResumablePaginator(BasePaginator):
            def __init__(self):
                super().__init__()
                self._resume_url: str | None = None
                self._has_next_page = False

            def init_request(self, request):
                if self._resume_url is not None:
                    request.url = self._resume_url

            def update_state(self, response, data=None):
                self._has_next_page = False

            def update_request(self, request):
                pass

            def set_resume_state(self, state):
                self._resume_url = state["url"]
                self._has_next_page = True

        client = RESTClient(base_url="https://api.example.com")
        list(
            client.paginate(
                path="/items",
                paginator=ResumablePaginator(),
                initial_paginator_state={"url": "https://api.example.com/resume-here"},
            )
        )

        prepared_request = mock_session.prepare_request.call_args.args[0]
        # The request URL should be the resumed URL, not the base "/items" path.
        assert prepared_request.url == "https://api.example.com/resume-here"

    @patch("posthog.temporal.data_imports.sources.common.rest_source.rest_client.requests.Session")
    def test_paginate_drops_none_params(self, MockSession) -> None:
        """``None`` values in ``params`` must be dropped before the request is
        prepared — otherwise ``requests`` serializes them as the literal string
        ``"None"`` in the query string."""
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()
        mock_session.send.return_value = _make_response({"data": []})

        client = RESTClient(base_url="https://api.example.com")
        list(
            client.paginate(
                path="/items",
                params={"limit": 100, "since": None, "until": None, "name": "alice"},
                paginator=SinglePagePaginator(),
            )
        )

        prepared_request = mock_session.prepare_request.call_args.args[0]
        assert prepared_request.params == {"limit": 100, "name": "alice"}

    @patch("posthog.temporal.data_imports.sources.common.rest_source.rest_client.requests.Session")
    def test_send_request_retries_on_429(self, MockSession) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()

        rate_limited = _make_response({"error": "rate limited"}, status_code=429)
        rate_limited.url = "https://api.example.com/items"
        ok = _make_response({"results": [{"id": 1}]})

        mock_session.send.side_effect = [rate_limited, ok]

        client = RESTClient(base_url="https://api.example.com")
        pages = list(client.paginate(path="/items", data_selector="results", paginator=SinglePagePaginator()))

        assert pages == [[{"id": 1}]]
        assert mock_session.send.call_count == 2

    @patch("posthog.temporal.data_imports.sources.common.rest_source.rest_client.requests.Session")
    def test_send_request_retries_on_500(self, MockSession) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()

        server_error = _make_response({"error": "internal"}, status_code=500)
        server_error.url = "https://api.example.com/items"
        ok = _make_response([{"id": 1}])

        mock_session.send.side_effect = [server_error, ok]

        client = RESTClient(base_url="https://api.example.com")
        pages = list(client.paginate(path="/items", paginator=SinglePagePaginator()))

        assert pages == [[{"id": 1}]]
        assert mock_session.send.call_count == 2

    @patch("posthog.temporal.data_imports.sources.common.rest_source.rest_client.requests.Session")
    def test_send_request_raises_after_max_retries(self, MockSession) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()

        error = _make_response({"error": "rate limited"}, status_code=429)
        error.url = "https://api.example.com/items"
        mock_session.send.return_value = error

        client = RESTClient(base_url="https://api.example.com")
        with pytest.raises(RESTClientRetryableError):
            list(client.paginate(path="/items", paginator=SinglePagePaginator()))

    @patch("posthog.temporal.data_imports.sources.common.rest_source.rest_client.requests.Session")
    def test_send_request_respects_retry_after_header(self, MockSession) -> None:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.return_value = MagicMock()

        rate_limited = _make_response({"error": "rate limited"}, status_code=429)
        rate_limited.url = "https://api.example.com/items"
        rate_limited.headers["Retry-After"] = "90"
        ok = _make_response({"results": [{"id": 1}]})

        mock_session.send.side_effect = [rate_limited, ok]

        client = RESTClient(base_url="https://api.example.com")
        pages = list(client.paginate(path="/items", data_selector="results", paginator=SinglePagePaginator()))

        assert pages == [[{"id": 1}]]
        assert mock_session.send.call_count == 2
