from collections.abc import Iterable

import pytest
from unittest.mock import MagicMock, patch

from products.conversations.backend.temporal.plain_import.client import (
    PlainAttachmentTooLargeError,
    PlainCredentials,
    PlainImportClient,
    validate_plain_credentials,
)

M = "products.conversations.backend.temporal.plain_import.client"


class _FakeStreamResponse:
    def __init__(self, *, headers: dict[str, str] | None = None, chunks: Iterable[bytes] = ()) -> None:
        self.status_code = 200
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


class TestValidatePlainCredentials:
    def test_rejects_invalid_region_without_request(self) -> None:
        credentials = PlainCredentials(api_key="key", region="eu")
        with patch(f"{M}.make_tracked_session") as mock_session:
            assert validate_plain_credentials(credentials) is False
            mock_session.assert_not_called()

    def test_returns_true_on_valid_response(self) -> None:
        credentials = PlainCredentials(api_key="key", region="uk")
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"threads": {"edges": []}}}
        mock_session.post.return_value = mock_response

        with patch(f"{M}.make_tracked_session", return_value=mock_session):
            assert validate_plain_credentials(credentials) is True
        mock_session.post.assert_called_once()
        assert "core-api.uk.plain.com" in mock_session.post.call_args.args[0]


class TestPlainImportClientInit:
    def test_rejects_invalid_region(self) -> None:
        with pytest.raises(ValueError, match="Invalid Plain region"):
            PlainImportClient(PlainCredentials(api_key="key", region="eu"))

    def test_pins_uk_and_us_hosts(self) -> None:
        uk = PlainImportClient(PlainCredentials(api_key="key", region="uk"))
        us = PlainImportClient(PlainCredentials(api_key="key", region="us"))
        assert uk._host == "core-api.uk.plain.com"
        assert us._host == "core-api.us.plain.com"


class TestListThreadIdsPage:
    def test_parses_page_and_end_of_stream(self) -> None:
        client = PlainImportClient(PlainCredentials(api_key="key", region="uk"))
        client._graphql = MagicMock(  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
            return_value={
                "threads": {
                    "edges": [{"node": {"id": "t_1"}}, {"node": {"id": "t_2"}}],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        )
        ids, cursor, end = client.list_thread_ids_page()
        assert ids == ["t_1", "t_2"]
        assert cursor is None
        assert end is True


class TestDownloadAttachmentSizeCap:
    def _client(self) -> PlainImportClient:
        client = PlainImportClient(PlainCredentials(api_key="key", region="uk"))
        client.create_attachment_download_url = MagicMock(  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
            return_value="https://cdn.example.com/file"
        )
        return client

    def test_content_length_precheck_aborts_before_reading_body(self) -> None:
        client = self._client()
        resp = _FakeStreamResponse(headers={"Content-Length": "11"}, chunks=[b"x" * 11])
        client._session = MagicMock()
        client._session.get.return_value = resp

        with pytest.raises(PlainAttachmentTooLargeError):
            client.download_attachment("att_1", max_bytes=10)
        assert resp.consumed_chunks == 0

    def test_streaming_aborts_when_lying_content_length(self) -> None:
        client = self._client()
        resp = _FakeStreamResponse(headers={}, chunks=[b"x" * 8, b"x" * 8])
        client._session = MagicMock()
        client._session.get.return_value = resp

        with pytest.raises(PlainAttachmentTooLargeError):
            client.download_attachment("att_1", max_bytes=10)

    def test_returns_bytes_within_cap(self) -> None:
        client = self._client()
        resp = _FakeStreamResponse(headers={"Content-Length": "6"}, chunks=[b"abc", b"def"])
        client._session = MagicMock()
        client._session.get.return_value = resp

        assert client.download_attachment("att_1", max_bytes=10) == b"abcdef"

    def test_refuses_non_https_download_url(self) -> None:
        client = PlainImportClient(PlainCredentials(api_key="key", region="uk"))
        client.create_attachment_download_url = MagicMock(  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
            return_value="http://cdn.example.com/file"
        )
        client._session = MagicMock()
        with pytest.raises(ValueError, match="non-https"):
            client.download_attachment("att_1", max_bytes=10)
        client._session.get.assert_not_called()
