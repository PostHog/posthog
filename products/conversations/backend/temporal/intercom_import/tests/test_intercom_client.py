from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests

from products.conversations.backend.temporal.intercom_import.client import (
    MAX_PART_PAGES,
    IntercomAttachmentDownloadError,
    IntercomAttachmentTooLargeError,
    IntercomCredentials,
    IntercomImportClient,
    IntercomIncompleteConversationError,
    IntercomNotFoundError,
    IntercomRateLimitError,
    is_retryable_error,
    validate_intercom_credentials,
)

M = "products.conversations.backend.temporal.intercom_import.client"
FAKE_TOKEN = "fake-intercom-token-for-tests"


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


def _client(region: str = "us") -> tuple[IntercomImportClient, MagicMock]:
    session = MagicMock()
    with patch(f"{M}.make_tracked_session", return_value=session):
        client = IntercomImportClient(IntercomCredentials(region=region, access_token=FAKE_TOKEN))
    return client, session


class TestIntercomImportClient:
    @pytest.mark.parametrize(
        "region,host",
        [("us", "api.intercom.io"), ("eu", "api.eu.intercom.io"), ("au", "api.au.intercom.io")],
    )
    def test_requests_go_to_the_regional_host_with_bearer_token(self, region: str, host: str) -> None:
        client, session = _client(region)
        session.request.return_value = _FakeResponse(json_body={"conversations": [{"id": "1"}], "pages": {}})

        ids, cursor = client.list_conversation_ids_page()

        method, url = session.request.call_args.args
        assert (method, url) == ("GET", f"https://{host}/conversations")
        assert session.request.call_args.kwargs["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"
        assert (ids, cursor) == (["1"], None)

    @pytest.mark.parametrize(
        "next_page",
        [
            pytest.param({"page": 2, "starting_after": "cursor-2"}, id="cursor_object"),
            pytest.param("https://api.intercom.io/conversations?per_page=150&starting_after=cursor-2", id="link"),
        ],
    )
    def test_pagination_returns_next_cursor_until_last_page(self, next_page: Any) -> None:
        client, session = _client()
        session.request.side_effect = [
            _FakeResponse(json_body={"conversations": [{"id": "1"}, {"id": "2"}], "pages": {"next": next_page}}),
            _FakeResponse(json_body={"conversations": [{"id": "3"}], "pages": {"page": 2}}),
        ]

        first = client.list_conversation_ids_page()
        second = client.list_conversation_ids_page(cursor=first[1])

        assert first == (["1", "2"], "cursor-2")
        assert second == (["3"], None)
        assert session.request.call_args.kwargs["params"]["starting_after"] == "cursor-2"

    def test_fetch_conversation_pages_through_all_parts_oldest_first(self) -> None:
        client, session = _client()

        def page(n: int, part_ids: list[str]) -> _FakeResponse:
            return _FakeResponse(
                json_body={
                    "id": "42",
                    "state": "open",
                    "conversation_parts": {
                        "conversation_parts": [{"id": pid} for pid in part_ids],
                        "pages": {"type": "pages", "page": n, "per_page": 500, "total_pages": 2},
                    },
                }
            )

        session.request.side_effect = [page(1, ["p1", "p2"]), page(2, ["p3"])]

        conversation = client.fetch_conversation("42")

        assert [p["id"] for p in conversation["conversation_parts"]["conversation_parts"]] == ["p1", "p2", "p3"]
        assert [c.kwargs["params"]["page"] for c in session.request.call_args_list] == [1, 2]
        assert session.request.call_args.kwargs["params"]["display_as"] == "plaintext"

    def test_fetch_contact_follows_merge_and_requests_unescaped_identity(self) -> None:
        client, session = _client()
        session.request.side_effect = [
            _FakeResponse(
                status_code=410, headers={"Link": '<https://api.intercom.io/contacts/abc123>; rel="canonical"'}
            ),
            _FakeResponse(json_body={"id": "abc123", "name": "Smith & Co", "email": "lee@example.com"}),
        ]

        contact = client.fetch_contact("old456")

        assert contact["name"] == "Smith & Co"
        assert [c.args[1] for c in session.request.call_args_list] == [
            "https://api.intercom.io/contacts/old456",
            "https://api.intercom.io/contacts/abc123",
        ]
        assert all(c.kwargs["params"]["escape_identity"] == "false" for c in session.request.call_args_list)

    def test_conversation_over_the_page_cap_fails_instead_of_returning_a_prefix(self) -> None:
        client, session = _client()
        session.request.side_effect = lambda *a, **kw: _FakeResponse(
            json_body={
                "id": "42",
                "conversation_parts": {
                    "conversation_parts": [{"id": f"p{kw['params']['page']}"}],
                    "pages": {"page": kw["params"]["page"], "total_pages": MAX_PART_PAGES + 1},
                },
            }
        )

        with pytest.raises(IntercomIncompleteConversationError):
            client.fetch_conversation("42")

        assert session.request.call_count == MAX_PART_PAGES

    def test_missing_contact_raises_not_found(self) -> None:
        client, session = _client()
        session.request.return_value = _FakeResponse(status_code=404)

        with pytest.raises(IntercomNotFoundError):
            client.fetch_contact("abc123")

    def test_rate_limit_beyond_budget_raises_for_temporal_retry(self) -> None:
        client, session = _client()
        session.request.return_value = _FakeResponse(status_code=429)

        with patch(f"{M}.time.sleep") as sleep, pytest.raises(IntercomRateLimitError):
            client.fetch_conversation("123")

        assert sleep.call_count == 3

    @pytest.mark.parametrize("conversation_id", ["../admins", "1?x=y", "1/parts", "1²"])
    def test_fetch_conversation_rejects_path_unsafe_ids(self, conversation_id: str) -> None:
        client, session = _client()
        with pytest.raises(ValueError):
            client.fetch_conversation(conversation_id)
        session.request.assert_not_called()


class TestIntercomAttachmentDownload:
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
            _FakeResponse(chunks=[b"abc", b"def"]),
        ]
        with self._pinned(responses) as pinned:
            data = client.download_attachment("https://downloads.example.com/i/o/1", max_bytes=100)

        assert data == b"abcdef"
        assert [c.args[0] for c in pinned.call_args_list] == [
            "https://downloads.example.com/i/o/1",
            "https://cdn.example.com/signed/file.png",
        ]
        for call in self.session.get.call_args_list:
            assert "headers" not in call.kwargs
            assert call.kwargs["allow_redirects"] is False

    def test_rejects_non_https_url(self) -> None:
        client, _ = _client()
        with self._pinned([]) as pinned, pytest.raises(ValueError):
            client.download_attachment("http://downloads.example.com/file", max_bytes=100)
        pinned.assert_not_called()

    @pytest.mark.parametrize("status_code,retryable", [(403, False), (404, False), (503, True)])
    def test_http_error_keeps_the_signed_url_out_of_the_message(self, status_code: int, retryable: bool) -> None:
        client, _ = _client()
        signed = "https://downloads.example.com/f?expires=1&signature=secret-sig"
        with self._pinned([_FakeResponse(status_code=status_code)]):
            with pytest.raises(IntercomAttachmentDownloadError) as caught:
                client.download_attachment(signed, max_bytes=100)

        assert "secret-sig" not in str(caught.value)
        assert caught.value.__cause__ is None and caught.value.__context__ is None
        assert is_retryable_error(caught.value) is retryable

    def test_transport_error_is_retryable_without_the_signed_url(self) -> None:
        client, _ = _client()
        signed = "https://downloads.example.com/f?expires=1&signature=secret-sig"
        with self._pinned([requests.ConnectionError(f"Max retries exceeded with url: {signed}")]):
            with pytest.raises(IntercomAttachmentDownloadError) as caught:
                client.download_attachment(signed, max_bytes=100)

        assert "secret-sig" not in str(caught.value)
        # `from None` hides the original requests error, whose message holds the signed URL.
        assert caught.value.__suppress_context__
        assert is_retryable_error(caught.value)

    def test_aborts_once_streamed_bytes_exceed_cap(self) -> None:
        client, _ = _client()
        with self._pinned([_FakeResponse(chunks=[b"x" * 60, b"x" * 60])]):
            with pytest.raises(IntercomAttachmentTooLargeError):
                client.download_attachment("https://downloads.example.com/file", max_bytes=100)


class TestValidateIntercomCredentials:
    def test_unknown_region_is_rejected_without_a_request(self) -> None:
        with patch(f"{M}.make_tracked_session") as make_session:
            assert validate_intercom_credentials(IntercomCredentials(region="mars", access_token=FAKE_TOKEN)) is False
        make_session.assert_not_called()

    @pytest.mark.parametrize("status_code,expected", [(200, True), (401, False), (403, False)])
    def test_probes_conversation_read_access(self, status_code: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = _FakeResponse(status_code=status_code)
        with patch(f"{M}.make_tracked_session", return_value=session):
            assert validate_intercom_credentials(IntercomCredentials(region="eu", access_token=FAKE_TOKEN)) is expected
        assert session.get.call_args.args[0] == "https://api.eu.intercom.io/conversations"

    def test_transport_error_counts_as_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = ConnectionError("dns failure")
        with patch(f"{M}.make_tracked_session", return_value=session):
            assert validate_intercom_credentials(IntercomCredentials(region="us", access_token=FAKE_TOKEN)) is False


def _http_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(response=response)


@pytest.mark.parametrize(
    "exc,expected",
    [
        pytest.param(IntercomRateLimitError("slow"), True, id="rate_limit"),
        pytest.param(requests.Timeout(), True, id="timeout"),
        pytest.param(requests.ConnectionError(), True, id="connection"),
        pytest.param(_http_error(503), True, id="server_error"),
        pytest.param(_http_error(404), False, id="not_found"),
        pytest.param(_http_error(403), False, id="expired_link"),
        pytest.param(ValueError("bad id"), False, id="bad_data"),
    ],
)
def test_is_retryable_error(exc: BaseException, expected: bool) -> None:
    assert is_retryable_error(exc) is expected
