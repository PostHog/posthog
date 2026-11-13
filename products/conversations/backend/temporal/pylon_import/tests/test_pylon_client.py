from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests

from products.conversations.backend.temporal.pylon_import.client import (
    MAX_MESSAGE_PAGES,
    MAX_RATE_LIMIT_RETRIES,
    PylonAttachmentDownloadError,
    PylonAttachmentTooLargeError,
    PylonCredentials,
    PylonImportClient,
    PylonIncompleteIssueError,
    PylonNotFoundError,
    PylonRateLimitError,
    is_retryable_error,
    resolve_pylon_credentials,
)

M = "products.conversations.backend.temporal.pylon_import.client"
FAKE_TOKEN = "pylon_api_fake-token-for-tests"
FAKE_EU_TOKEN = "pylon_api_eu_fake-token-for-tests"
ISSUE_ID = "0a1b2c3d-0000-4000-8000-000000000001"


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        chunks: Iterable[bytes] = (),
        json_body: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = list(chunks)
        self._json = json_body or {}

    @property
    def is_redirect(self) -> bool:
        return self.status_code in (301, 302, 303, 307, 308)

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size: int = 0) -> Iterable[bytes]:
        yield from self._chunks

    def json(self) -> dict[str, Any]:
        return self._json


def _client(region: str = "us") -> tuple[PylonImportClient, MagicMock]:
    session = MagicMock()
    with patch(f"{M}.make_tracked_session", return_value=session):
        client = PylonImportClient(PylonCredentials(region=region, api_token=FAKE_TOKEN))
    return client, session


def _page(items: list[dict[str, Any]], cursor: str | None = None) -> _FakeResponse:
    pagination = {"cursor": cursor, "has_next_page": True} if cursor else {"has_next_page": False}
    return _FakeResponse(json_body={"data": items, "pagination": pagination, "request_id": "r"})


class TestPylonImportClient:
    @pytest.mark.parametrize("region,host", [("us", "api.usepylon.com"), ("eu", "api.eu.usepylon.com")])
    def test_issue_search_goes_to_the_regional_host_oldest_first(self, region: str, host: str) -> None:
        client, session = _client(region)
        session.request.return_value = _page([{"id": "i-1"}])

        ids, cursor = client.list_issue_ids_page()

        method, url = session.request.call_args.args
        assert (method, url) == ("POST", f"https://{host}/issues/search")
        assert session.request.call_args.kwargs["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"
        assert session.request.call_args.kwargs["json"]["sort"] == [{"field": "created_at", "order": "asc"}]
        assert (ids, cursor) == (["i-1"], None)

    def test_issue_pagination_sends_the_cursor_until_the_last_page(self) -> None:
        client, session = _client()
        session.request.side_effect = [_page([{"id": "i-1"}, {"id": "i-2"}], cursor="c2"), _page([{"id": "i-3"}])]

        first = client.list_issue_ids_page()
        second = client.list_issue_ids_page(cursor=first[1])

        assert first == (["i-1", "i-2"], "c2")
        assert second == (["i-3"], None)
        assert session.request.call_args.kwargs["json"]["cursor"] == "c2"

    def test_cursor_that_does_not_advance_ends_the_listing(self) -> None:
        client, session = _client()
        session.request.return_value = _page([{"id": "i-1"}], cursor="c2")

        assert client.list_issue_ids_page(cursor="c2") == (["i-1"], None)

    def test_fetch_messages_pages_through_every_message(self) -> None:
        client, session = _client()
        session.request.side_effect = [_page([{"id": "m1"}, {"id": "m2"}], cursor="c2"), _page([{"id": "m3"}])]

        messages = client.fetch_messages(ISSUE_ID)

        assert [m["id"] for m in messages] == ["m1", "m2", "m3"]
        assert session.request.call_args.args == ("GET", f"https://api.usepylon.com/issues/{ISSUE_ID}/messages")
        assert [c.kwargs["params"].get("cursor") for c in session.request.call_args_list] == [None, "c2"]

    def test_issue_over_the_page_cap_fails_instead_of_returning_a_prefix(self) -> None:
        client, session = _client()
        pages = iter(range(1, MAX_MESSAGE_PAGES + 2))
        session.request.side_effect = lambda *a, **kw: _page([{"id": "m"}], cursor=f"c{next(pages)}")

        with pytest.raises(PylonIncompleteIssueError):
            client.fetch_messages(ISSUE_ID)

        assert session.request.call_count == MAX_MESSAGE_PAGES

    def test_missing_contact_raises_not_found(self) -> None:
        client, session = _client()
        session.request.return_value = _FakeResponse(status_code=404)

        with pytest.raises(PylonNotFoundError):
            client.fetch_contact("contact-1")

    def test_issue_statuses_are_fetched_once(self) -> None:
        client, session = _client()
        session.request.return_value = _FakeResponse(
            json_body={"data": [{"slug": "Escalated", "category": "on_hold"}, {"slug": "new", "category": "new"}]}
        )

        assert client.issue_status_categories() == {"escalated": "on_hold", "new": "new"}
        client.issue_status_categories()

        assert session.request.call_count == 1

    def test_rate_limited_request_waits_for_retry_after_then_succeeds(self) -> None:
        client, session = _client()
        session.request.side_effect = [
            _FakeResponse(status_code=429, headers={"Retry-After": "3"}),
            _FakeResponse(json_body={"data": {"id": ISSUE_ID}}),
        ]

        with patch(f"{M}.time.sleep") as sleep, patch(f"{M}.random.uniform", return_value=0.0):
            issue = client.fetch_issue(ISSUE_ID)

        assert issue == {"id": ISSUE_ID}
        assert [c.args[0] for c in sleep.call_args_list] == [3]

    def test_rate_limit_beyond_budget_raises_for_temporal_retry(self) -> None:
        client, session = _client()
        session.request.return_value = _FakeResponse(status_code=429, headers={"Retry-After": "1"})

        with patch(f"{M}.time.sleep") as sleep, pytest.raises(PylonRateLimitError):
            client.fetch_issue(ISSUE_ID)

        assert sleep.call_count == MAX_RATE_LIMIT_RETRIES

    @pytest.mark.parametrize(
        "headers,expected_sleeps",
        [
            pytest.param({"X-Rate-Limit-Remaining": "2", "X-Rate-Limit-Limit": "120"}, [1.0], id="nearly_spent"),
            pytest.param({"X-Rate-Limit-Remaining": "80", "X-Rate-Limit-Limit": "120"}, [], id="plenty_left"),
            pytest.param({}, [], id="no_headers"),
        ],
    )
    def test_requests_slow_down_before_the_allowance_runs_out(
        self, headers: dict[str, str], expected_sleeps: list[float]
    ) -> None:
        client, session = _client()
        session.request.return_value = _FakeResponse(headers=headers, json_body={"data": {"id": ISSUE_ID}})

        with patch(f"{M}.time.sleep") as sleep:
            client.fetch_issue(ISSUE_ID)

        assert [c.args[0] for c in sleep.call_args_list] == expected_sleeps

    @pytest.mark.parametrize("issue_id", ["../users", "1?x=y", "1/messages", "1²"])
    def test_fetch_rejects_path_unsafe_ids(self, issue_id: str) -> None:
        client, session = _client()
        with pytest.raises(ValueError):
            client.fetch_messages(issue_id)
        session.request.assert_not_called()


class TestPylonAttachmentDownload:
    @contextmanager
    def _pinned(self, responses: Sequence[_FakeResponse | Exception]) -> Iterator[MagicMock]:
        session = MagicMock()
        session.get.side_effect = responses
        self.session = session

        @contextmanager
        def fake_pinned_session(url: str) -> Iterator[MagicMock]:
            yield session

        with patch(f"{M}.pinned_session", side_effect=fake_pinned_session) as pinned:
            yield pinned

    def test_follows_redirect_without_sending_the_token(self) -> None:
        client, _ = _client()
        responses = [
            _FakeResponse(status_code=302, headers={"Location": "https://cdn.example.com/signed/file.png"}),
            _FakeResponse(chunks=[b"abc", b"def"], headers={"Content-Type": "image/png; charset=binary"}),
        ]
        with self._pinned(responses) as pinned:
            attachment = client.download_attachment("https://files.example.com/f/1", max_bytes=100)

        assert (attachment.content, attachment.content_type) == (b"abcdef", "image/png")
        assert [c.args[0] for c in pinned.call_args_list] == [
            "https://files.example.com/f/1",
            "https://cdn.example.com/signed/file.png",
        ]
        for call in self.session.get.call_args_list:
            assert "headers" not in call.kwargs
            assert call.kwargs["allow_redirects"] is False

    def test_rejects_non_https_url(self) -> None:
        client, _ = _client()
        with self._pinned([]) as pinned, pytest.raises(ValueError):
            client.download_attachment("http://files.example.com/file", max_bytes=100)
        pinned.assert_not_called()

    @pytest.mark.parametrize("status_code,retryable", [(403, False), (404, False), (503, True)])
    def test_http_error_keeps_the_signed_url_out_of_the_message(self, status_code: int, retryable: bool) -> None:
        client, _ = _client()
        signed = "https://files.example.com/f?signature=secret-sig"
        with self._pinned([_FakeResponse(status_code=status_code)]):
            with pytest.raises(PylonAttachmentDownloadError) as caught:
                client.download_attachment(signed, max_bytes=100)

        assert "secret-sig" not in str(caught.value)
        assert caught.value.__cause__ is None and caught.value.__context__ is None
        assert is_retryable_error(caught.value) is retryable

    def test_transport_error_is_retryable_without_the_signed_url(self) -> None:
        client, _ = _client()
        signed = "https://files.example.com/f?signature=secret-sig"
        with self._pinned([requests.ConnectionError(f"Max retries exceeded with url: {signed}")]):
            with pytest.raises(PylonAttachmentDownloadError) as caught:
                client.download_attachment(signed, max_bytes=100)

        assert "secret-sig" not in str(caught.value)
        assert caught.value.__suppress_context__
        assert is_retryable_error(caught.value)

    def test_aborts_once_streamed_bytes_exceed_cap(self) -> None:
        client, _ = _client()
        with self._pinned([_FakeResponse(chunks=[b"x" * 60, b"x" * 60])]):
            with pytest.raises(PylonAttachmentTooLargeError):
                client.download_attachment("https://files.example.com/file", max_bytes=100)


class TestResolvePylonCredentials:
    def _resolve(self, token: str, responses: Sequence[_FakeResponse | Exception]) -> tuple[Any, list[str]]:
        session = MagicMock()
        session.post.side_effect = responses
        with patch(f"{M}.make_tracked_session", return_value=session):
            credentials = resolve_pylon_credentials(token)
        return credentials, [c.args[0] for c in session.post.call_args_list]

    @pytest.mark.parametrize(
        "token,statuses,expected_region,expected_hosts",
        [
            pytest.param(FAKE_TOKEN, [200], "us", ["api.usepylon.com"], id="us_token"),
            pytest.param(FAKE_EU_TOKEN, [200], "eu", ["api.eu.usepylon.com"], id="eu_prefix_goes_to_eu_first"),
            # A token created before region prefixes existed can belong to either region.
            pytest.param(
                "legacy-token", [401, 200], "eu", ["api.usepylon.com", "api.eu.usepylon.com"], id="legacy_eu_token"
            ),
            pytest.param(FAKE_TOKEN, [401, 401], None, ["api.usepylon.com", "api.eu.usepylon.com"], id="rejected"),
            # The role cannot read issues, so the import would fail later.
            pytest.param(FAKE_TOKEN, [403], None, ["api.usepylon.com"], id="no_issue_access"),
        ],
    )
    def test_finds_the_region_that_can_read_issues(
        self, token: str, statuses: list[int], expected_region: str | None, expected_hosts: list[str]
    ) -> None:
        credentials, urls = self._resolve(token, [_FakeResponse(status_code=s) for s in statuses])

        assert (credentials.region if credentials else None) == expected_region
        assert urls == [f"https://{host}/issues/search" for host in expected_hosts]

    def test_transport_error_counts_as_invalid(self) -> None:
        credentials, _ = self._resolve(FAKE_TOKEN, [ConnectionError("dns failure")])

        assert credentials is None

    def test_token_stays_out_of_the_credentials_repr(self) -> None:
        assert FAKE_TOKEN not in repr(PylonCredentials(region="us", api_token=FAKE_TOKEN))


def _http_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(response=response)


@pytest.mark.parametrize(
    "exc,expected",
    [
        pytest.param(PylonRateLimitError("slow"), True, id="rate_limit"),
        pytest.param(requests.Timeout(), True, id="timeout"),
        pytest.param(requests.ConnectionError(), True, id="connection"),
        pytest.param(requests.exceptions.ChunkedEncodingError(), True, id="body_interrupted"),
        pytest.param(_http_error(503), True, id="server_error"),
        pytest.param(_http_error(404), False, id="not_found"),
        pytest.param(_http_error(401), False, id="revoked_token"),
        pytest.param(ValueError("bad id"), False, id="bad_data"),
    ],
)
def test_is_retryable_error(exc: BaseException, expected: bool) -> None:
    assert is_retryable_error(exc) is expected
