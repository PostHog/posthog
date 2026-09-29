import os
import asyncio
from contextlib import suppress
from ipaddress import ip_address

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from posthog.security.pinned_aiohttp import MAX_RESPONSE_BYTES, ResponseLimitExceeded, pinned_request
from posthog.security.pinned_requests import SSRFBlockedError
from posthog.security.url_validation import PinnedUrlVerdict

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("status", [200, 422])
@pytest.mark.parametrize("limit", ["content_length", "streamed", "compressed"])
async def test_response_size_is_bounded(status: int, limit: str) -> None:
    response = MagicMock(
        status=status,
        content_length=MAX_RESPONSE_BYTES + 1 if limit == "content_length" else None,
        headers={"Content-Encoding": "gzip"} if limit == "compressed" else {},
    )
    response.__aenter__.return_value = response
    response.content.iter_chunked.return_value.__aiter__.return_value = [b"x" * 8192] * (MAX_RESPONSE_BYTES // 8192 + 1)
    with (
        patch("aiohttp.ClientSession.request", new_callable=AsyncMock, return_value=response),
        pytest.raises(ResponseLimitExceeded),
    ):
        await pinned_request(
            "POST", "https://example.com", headers={}, json={}, timeout=1, read_body_statuses=(200, 422)
        )
    response.__aexit__.assert_awaited_once()


@pytest.mark.parametrize("status", [302, 429])
async def test_unneeded_bodies_are_not_read_or_redirected(status: int) -> None:
    response = MagicMock(status=status, headers={"Location": "https://other.example.com", "Retry-After": "15"})
    with patch("aiohttp.ClientSession.request", new_callable=AsyncMock, return_value=response) as request:
        result = await pinned_request("POST", "https://example.com", headers={}, json={}, timeout=1)
    assert result.status_code == status
    assert result.headers["Retry-After"] == "15"
    assert result.content == b""
    response.content.iter_chunked.assert_not_called()
    assert request.call_args.kwargs["allow_redirects"] is False
    response.__aexit__.assert_awaited_once()


@pytest.mark.parametrize("url", ["https://127.0.0.1", "https://example.com"])
async def test_private_destinations_are_blocked_before_sending(url: str) -> None:
    with (
        override_settings(DEBUG=False, TEST=False),
        patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("127.0.0.1")}),
        patch("aiohttp.ClientSession.request", new_callable=AsyncMock) as request,
        pytest.raises(SSRFBlockedError),
    ):
        await pinned_request("POST", url, headers={"Authorization": "Bearer fake-key"}, json={}, timeout=1)
    request.assert_not_called()


@pytest.mark.parametrize("phase", ["headers", "body"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_deadline_and_cancellation_close_a_pinned_connection(phase: str, cancel: bool) -> None:
    started = asyncio.Event()
    disconnected = asyncio.Event()
    received_headers: list[bytes] = []
    loop = asyncio.get_running_loop()

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        received_headers.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 1000000\r\n")
        writer.write(b"\r\n" if phase == "body" else b"X-Slow: ")
        timer: asyncio.TimerHandle

        def drip() -> None:
            nonlocal timer
            writer.write(b"x")
            timer = loop.call_later(0.01, drip)

        timer = loop.call_later(0.01, drip)
        started.set()
        try:
            with suppress(ConnectionError):
                await reader.read()
        finally:
            timer.cancel()
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()
            disconnected.set()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        with (
            patch(
                "posthog.security.pinned_aiohttp.validate_url_and_pin_ips",
                return_value=PinnedUrlVerdict(allowed=True, reason=None, pinned_ips={ip_address("127.0.0.1")}),
            ),
            patch.dict(os.environ, {"http_proxy": "http://proxy.invalid:9", "no_proxy": ""}),
        ):
            task = asyncio.create_task(
                pinned_request("POST", f"http://example.com:{port}", headers={}, json={}, timeout=0.2)
            )
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                if cancel:
                    task.cancel()
                with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
                    await task
                await asyncio.wait_for(disconnected.wait(), timeout=5)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
    assert f"Host: example.com:{port}\r\n".encode() in received_headers[0]
