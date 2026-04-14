import json
from typing import Any

from unittest.mock import MagicMock, patch

from requests import Response

from posthog.temporal.data_imports.sources.common.rest_source.exceptions import IgnoreResponseException
from posthog.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator, SinglePagePaginator
from posthog.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient


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
