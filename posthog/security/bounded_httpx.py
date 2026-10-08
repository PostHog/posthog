import asyncio
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

from django.utils.asyncio import async_unsafe

import httpx


class _BoundedResponseStream(httpx.SyncByteStream):
    def __init__(self, transport: "BoundedHTTPTransport", request: httpx.Request) -> None:
        self._owner = transport
        self._request = request
        self._transport = httpx.AsyncHTTPTransport(**transport.transport_kwargs)
        self._runner = asyncio.Runner()
        self._deadline = self._runner.get_loop().time() + transport.total_timeout
        self._response: httpx.Response | None = None
        self._closed = False

    async def _wait[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        if asyncio.get_running_loop().time() >= self._deadline:
            raise TimeoutError
        async with asyncio.timeout_at(self._deadline):
            return await operation()

    def _run[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        try:
            return self._runner.run(self._wait(operation))
        except TimeoutError as error:
            raise httpx.ReadTimeout(
                "The endpoint exceeded the total request deadline.", request=self._request
            ) from error

    def open(self) -> httpx.Response:
        # Refuse compression so a small wire response cannot expand beyond the byte limit.
        self._request.headers["Accept-Encoding"] = "identity"
        self._request.read()
        self._response = self._run(lambda: self._transport.handle_async_request(self._request))
        encoding = self._response.headers.get("Content-Encoding", "identity").lower().strip()
        if encoding != "identity":
            raise httpx.DecodingError("The endpoint must return an uncompressed response.", request=self._request)
        content_length = self._response.headers.get("Content-Length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                raise httpx.RemoteProtocolError("Invalid Content-Length.", request=self._request) from None
            if length < 0 or length > self._owner.max_response_bytes:
                raise httpx.DecodingError("The endpoint response exceeds the size limit.", request=self._request)
        return httpx.Response(
            self._response.status_code,
            headers=self._response.headers,
            stream=self,
            extensions=self._response.extensions,
        )

    def __iter__(self) -> Iterator[bytes]:
        if self._response is None or self._closed:
            raise httpx.StreamClosed()
        iterator = self._response.aiter_raw()
        size = 0
        try:
            while True:
                try:
                    chunk = self._run(lambda: anext(iterator))
                except StopAsyncIteration:
                    break
                size += len(chunk)
                if size > self._owner.max_response_bytes:
                    raise httpx.DecodingError("The endpoint response exceeds the size limit.", request=self._request)
                yield chunk
        finally:
            self.close()

    async def _close(self) -> None:
        try:
            if self._response is not None:
                await self._response.aclose()
        finally:
            await self._transport.aclose()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._runner.run(self._close())
        finally:
            self._runner.close()
            self._owner.streams.discard(self)


class BoundedHTTPTransport(httpx.BaseTransport):
    """Sync HTTPX interface with cancellable I/O and a bounded response body.

    Each response owns its async transport and event loop until it is consumed or closed.
    Connections are not pooled across requests. No background request survives a timeout.
    """

    def __init__(self, *, total_timeout: float, max_response_bytes: int, **transport_kwargs: Any) -> None:
        if total_timeout <= 0 or max_response_bytes <= 0:
            raise ValueError("Request limits must be positive.")
        self.total_timeout = total_timeout
        self.max_response_bytes = max_response_bytes
        self.transport_kwargs = transport_kwargs
        self.streams: set[_BoundedResponseStream] = set()

    @async_unsafe("Bounded HTTP requests must run in a synchronous worker.")
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        stream = _BoundedResponseStream(self, request)
        self.streams.add(stream)
        try:
            return stream.open()
        except BaseException:
            stream.close()
            raise

    def close(self) -> None:
        for stream in list(self.streams):
            stream.close()
