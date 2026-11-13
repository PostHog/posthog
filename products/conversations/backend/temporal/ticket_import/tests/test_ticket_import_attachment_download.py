from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager

import pytest
from unittest.mock import MagicMock, patch

import requests

from posthog.security.pinned_requests import SSRFBlockedError
from posthog.security.url_validation import UNRESOLVED_HOST_REASON

from products.conversations.backend.temporal.ticket_import.attachment_download import (
    MAX_DNS_RETRIES,
    MAX_RATE_LIMIT_RETRIES,
    AttachmentDownloadError,
    AttachmentTooLargeError,
    download_attachment,
)

M = "products.conversations.backend.temporal.ticket_import.attachment_download"
URL = "https://files.example.com/file"


class _FakeResponse:
    def __init__(
        self, *, status_code: int = 200, headers: dict[str, str] | None = None, chunks: Iterable[bytes] = ()
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = list(chunks)

    @property
    def is_redirect(self) -> bool:
        return self.status_code in (301, 302, 303, 307, 308)

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def iter_content(self, chunk_size: int = 0) -> Iterable[bytes]:
        yield from self._chunks


class TestAttachmentDownload:
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

    def test_follows_redirect_without_credentials_and_asks_for_stored_bytes(self) -> None:
        responses = [
            _FakeResponse(status_code=302, headers={"Location": "https://cdn.example.com/signed/file.png"}),
            _FakeResponse(chunks=[b"abc", b"def"], headers={"Content-Type": "image/png; charset=binary"}),
        ]
        with self._pinned(responses) as pinned:
            attachment = download_attachment("https://files.example.com/f/1", max_bytes=100)

        assert (attachment.content, attachment.content_type) == (b"abcdef", "image/png")
        assert [c.args[0] for c in pinned.call_args_list] == [
            "https://files.example.com/f/1",
            "https://cdn.example.com/signed/file.png",
        ]
        for call in self.session.get.call_args_list:
            assert call.kwargs["headers"] == {"Accept-Encoding": "identity"}
            assert call.kwargs["allow_redirects"] is False

    def test_rejects_non_https_url(self) -> None:
        with self._pinned([]) as pinned, pytest.raises(ValueError):
            download_attachment("http://files.example.com/file", max_bytes=100)
        pinned.assert_not_called()

    @pytest.mark.parametrize("encoding", ["gzip", "br", "deflate"])
    def test_refuses_an_encoded_body_before_reading_it(self, encoding: str) -> None:
        response = _FakeResponse(headers={"Content-Encoding": encoding})
        response.iter_content = MagicMock()  # type: ignore[method-assign]
        with self._pinned([response]), pytest.raises(ValueError):
            download_attachment(URL, max_bytes=100)
        response.iter_content.assert_not_called()

    @pytest.mark.parametrize("status_code,retryable", [(403, False), (404, False), (429, True), (503, True)])
    def test_http_error_keeps_the_signed_url_out_of_the_message(self, status_code: int, retryable: bool) -> None:
        signed = "https://files.example.com/f?expires=1&signature=secret-sig"
        responses = [_FakeResponse(status_code=status_code)] * (MAX_RATE_LIMIT_RETRIES + 1)
        with self._pinned(responses), patch(f"{M}.time.sleep"):
            with pytest.raises(AttachmentDownloadError) as caught:
                download_attachment(signed, max_bytes=100)

        assert "secret-sig" not in str(caught.value)
        assert caught.value.__cause__ is None and caught.value.__context__ is None
        assert caught.value.retryable is retryable

    def test_rate_limited_download_waits_for_retry_after_then_succeeds(self) -> None:
        responses = [_FakeResponse(status_code=429, headers={"Retry-After": "2"}), _FakeResponse(chunks=[b"abc"])]
        with self._pinned(responses), patch(f"{M}.time.sleep") as sleep:
            attachment = download_attachment(URL, max_bytes=100)

        assert attachment.content == b"abc"
        assert [c.args[0] for c in sleep.call_args_list] == [2]

    @pytest.mark.parametrize(
        "failures,expected_attempts,downloaded",
        [
            pytest.param([UNRESOLVED_HOST_REASON], 2, True, id="dns_recovers"),
            pytest.param([UNRESOLVED_HOST_REASON] * 5, MAX_DNS_RETRIES + 1, False, id="host_stays_unresolved"),
            pytest.param(["Disallowed target IP: 10.0.0.1"], 1, False, id="blocked_address_is_not_retried"),
        ],
    )
    def test_unresolved_host_is_retried_before_the_file_is_given_up(
        self, failures: list[str], expected_attempts: int, downloaded: bool
    ) -> None:
        session = MagicMock()
        session.get.return_value = _FakeResponse(chunks=[b"abc"])

        @contextmanager
        def resolved(url: str) -> Iterator[MagicMock]:
            yield session

        outcomes = [SSRFBlockedError(reason) for reason in failures] + [resolved(URL)]
        with patch(f"{M}.pinned_session", side_effect=outcomes) as pinned, patch(f"{M}.time.sleep"):
            if downloaded:
                assert download_attachment(URL, max_bytes=100).content == b"abc"
            else:
                with pytest.raises(SSRFBlockedError):
                    download_attachment(URL, max_bytes=100)

        assert pinned.call_count == expected_attempts

    def test_transport_error_is_retryable_without_the_signed_url(self) -> None:
        signed = "https://files.example.com/f?expires=1&signature=secret-sig"
        with self._pinned([requests.ConnectionError(f"Max retries exceeded with url: {signed}")]):
            with pytest.raises(AttachmentDownloadError) as caught:
                download_attachment(signed, max_bytes=100)

        assert "secret-sig" not in str(caught.value)
        # `from None` hides the original requests error, whose message holds the signed URL.
        assert caught.value.__suppress_context__
        assert caught.value.retryable

    def test_aborts_once_streamed_bytes_exceed_cap(self) -> None:
        with self._pinned([_FakeResponse(chunks=[b"x" * 60, b"x" * 60])]):
            with pytest.raises(AttachmentTooLargeError) as caught:
                download_attachment(URL, max_bytes=100)

        assert caught.value.bytes_read == 120
