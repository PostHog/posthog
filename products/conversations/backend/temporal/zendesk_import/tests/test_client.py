from collections.abc import Iterable

import pytest
from unittest.mock import MagicMock, patch

from products.conversations.backend.temporal.zendesk_import.client import (
    ZendeskAttachmentTooLargeError,
    ZendeskCredentials,
    ZendeskImportClient,
    validate_zendesk_credentials,
)

M = "products.conversations.backend.temporal.zendesk_import.client"


class _FakeStreamResponse:
    def __init__(
        self, *, status_code: int = 200, headers: dict[str, str] | None = None, chunks: Iterable[bytes] = ()
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = list(chunks)
        self.consumed_chunks = 0

    def __enter__(self) -> "_FakeStreamResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        pass

    def iter_content(self, chunk_size: int = 0) -> Iterable[bytes]:
        for chunk in self._chunks:
            self.consumed_chunks += 1
            yield chunk


class TestValidateZendeskCredentials:
    @pytest.mark.parametrize(
        "subdomain",
        [
            # A `#` turns the rest of the base URL into a fragment, so the real host would become
            # the attacker value instead of "<label>.zendesk.com" — the Basic auth token must not
            # be sent there.
            pytest.param("attacker.example#", id="host_fragment"),
            pytest.param("169.254.169.254#", id="metadata_ip_fragment"),
            pytest.param("foo.bar", id="multi_label"),
            pytest.param("foo@bar", id="userinfo"),
        ],
    )
    def test_rejects_host_retargeting_subdomain_without_request(self, subdomain: str) -> None:
        credentials = ZendeskCredentials(subdomain=subdomain, email_address="user@example.com", api_token="token")

        with patch(f"{M}.make_tracked_session") as mock_session:
            assert validate_zendesk_credentials(credentials) is False
            mock_session.assert_not_called()


class TestDownloadAttachmentSizeCap:
    def _client(self) -> ZendeskImportClient:
        return ZendeskImportClient(
            ZendeskCredentials(subdomain="acme", email_address="agent@acme.com", api_token="tok")
        )

    def test_content_length_precheck_aborts_before_reading_body(self) -> None:
        client = self._client()
        resp = _FakeStreamResponse(headers={"Content-Length": "11"}, chunks=[b"x" * 11])
        client._session = MagicMock()
        client._session.get.return_value = resp

        with pytest.raises(ZendeskAttachmentTooLargeError):
            client.download_attachment("https://acme.zendesk.com/a", max_bytes=10)
        # Declared oversize is rejected without streaming any chunk into memory.
        assert resp.consumed_chunks == 0

    def test_streaming_aborts_when_lying_content_length(self) -> None:
        # No/undersized Content-Length must not let an oversized body through — the
        # chunked read has to abort once the running total crosses the cap.
        client = self._client()
        resp = _FakeStreamResponse(headers={}, chunks=[b"x" * 8, b"x" * 8])
        client._session = MagicMock()
        client._session.get.return_value = resp

        with pytest.raises(ZendeskAttachmentTooLargeError):
            client.download_attachment("https://acme.zendesk.com/a", max_bytes=10)

    def test_returns_bytes_within_cap(self) -> None:
        client = self._client()
        resp = _FakeStreamResponse(headers={"Content-Length": "6"}, chunks=[b"abc", b"def"])
        client._session = MagicMock()
        client._session.get.return_value = resp

        assert client.download_attachment("https://acme.zendesk.com/a", max_bytes=10) == b"abcdef"


class TestDownloadAttachmentRedirects:
    def _client(self) -> ZendeskImportClient:
        return ZendeskImportClient(
            ZendeskCredentials(subdomain="acme", email_address="agent@acme.com", api_token="tok")
        )

    def test_follows_offhost_cdn_redirect_dropping_auth(self) -> None:
        # content_url is on the Zendesk host and 302s to an external CDN. We must follow the hop,
        # but the reusable Zendesk token must NOT be sent to the CDN.
        client = self._client()
        redirect = _FakeStreamResponse(status_code=302, headers={"Location": "https://cdn.zdusercontent.com/blob"})
        final = _FakeStreamResponse(headers={"Content-Length": "3"}, chunks=[b"abc"])
        client._session = MagicMock()
        client._session.get.side_effect = [redirect, final]

        with patch(f"{M}.is_url_allowed", return_value=(True, None)):
            assert client.download_attachment("https://acme.zendesk.com/attachments/x", max_bytes=10) == b"abc"

        first_headers = client._session.get.call_args_list[0].kwargs["headers"]
        second_headers = client._session.get.call_args_list[1].kwargs["headers"]
        assert "Authorization" in first_headers
        assert "Authorization" not in second_headers

    def test_refuses_redirect_to_internal_host(self) -> None:
        # A 302 pointing at an internal/metadata host must be refused before the followed request
        # goes out — the session no longer auto-follows, and the SSRF allowlist blocks the hop.
        client = self._client()
        redirect = _FakeStreamResponse(
            status_code=302, headers={"Location": "https://169.254.169.254/latest/meta-data/"}
        )
        client._session = MagicMock()
        client._session.get.side_effect = [redirect]

        with patch(f"{M}.is_url_allowed", return_value=(False, "Disallowed target IP")):
            with pytest.raises(ValueError):
                client.download_attachment("https://acme.zendesk.com/attachments/x", max_bytes=10)
        assert client._session.get.call_count == 1


class TestExpectedHostGuard:
    def _client(self) -> ZendeskImportClient:
        return ZendeskImportClient(
            ZendeskCredentials(subdomain="acme", email_address="agent@acme.com", api_token="tok")
        )

    @pytest.mark.parametrize(
        "url",
        [
            # Right host, wrong scheme: a host-only check would pass and send the Basic auth token
            # over cleartext http. Both the plaintext downgrade and any off-host redirect must be
            # refused before a request (and its Authorization header) goes out.
            pytest.param("http://acme.zendesk.com/api/v2/tickets/1/comments.json", id="http_downgrade"),
            pytest.param("https://evil.example.com/steal", id="off_host"),
            pytest.param("https://acme.zendesk.com.evil.com/steal", id="suffix_host"),
        ],
    )
    def test_download_attachment_refuses_and_sends_nothing(self, url: str) -> None:
        client = self._client()
        client._session = MagicMock()

        with pytest.raises(ValueError):
            client.download_attachment(url, max_bytes=10)
        client._session.get.assert_not_called()

    def test_request_refuses_http_absolute_url_and_sends_nothing(self) -> None:
        # `next_page` in a comments response is an absolute URL echoed straight into _request; an
        # http:// value must be rejected before the token-bearing request is issued.
        client = self._client()
        client._session = MagicMock()

        with pytest.raises(ValueError):
            client._request("GET", "http://acme.zendesk.com/api/v2/tickets/1/comments.json")
        client._session.request.assert_not_called()
