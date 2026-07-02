from collections.abc import AsyncIterator, Iterator
from http import HTTPStatus
from typing import cast

from unittest import mock

from django.http import StreamingHttpResponse

from prometheus_client import REGISTRY

from posthog.api.streaming import _instrument_stream, sse_streaming_response, streaming_response


def _gen() -> Iterator[bytes]:
    yield b"data: hello\n\n"


class TestSSEStreamingResponse:
    def test_releases_db_connections_before_streaming(self):
        idle = mock.Mock(in_atomic_block=False)
        with mock.patch("posthog.api.streaming.connections") as connections:
            connections.all.return_value = [idle]
            sse_streaming_response(_gen())
        connections.all.assert_called_once_with(initialized_only=True)
        idle.close.assert_called_once()

    def test_does_not_sever_connections_with_an_open_transaction(self):
        in_transaction = mock.Mock(in_atomic_block=True)
        with mock.patch("posthog.api.streaming.connections") as connections:
            connections.all.return_value = [in_transaction]
            sse_streaming_response(_gen())
        in_transaction.close.assert_not_called()

    def test_sets_event_stream_content_type_and_default_headers(self):
        response = sse_streaming_response(_gen())
        assert isinstance(response, StreamingHttpResponse)
        assert response.headers["Content-Type"] == "text/event-stream"
        assert response.headers["Cache-Control"] == "no-cache, no-transform"
        assert response.headers["X-Accel-Buffering"] == "no"
        assert response.status_code == HTTPStatus.OK

    def test_caller_headers_and_status_override_defaults(self):
        response = sse_streaming_response(
            _gen(),
            status=HTTPStatus.ACCEPTED,
            headers={"Cache-Control": "no-cache", "X-Custom": "1"},
        )
        assert response.status_code == HTTPStatus.ACCEPTED
        assert response.headers["Cache-Control"] == "no-cache"
        assert response.headers["X-Accel-Buffering"] == "no"
        assert response.headers["X-Custom"] == "1"


def _sync_content(response: StreamingHttpResponse) -> Iterator[bytes]:
    # streaming_content is typed as a sync/async union; these tests construct
    # the response from a sync iterator, so the cast is safe.
    return cast(Iterator[bytes], response.streaming_content)


def _async_content(response: StreamingHttpResponse) -> AsyncIterator[bytes]:
    return cast(AsyncIterator[bytes], response.streaming_content)


def _open_connections(endpoint: str) -> float:
    return REGISTRY.get_sample_value("posthog_open_sse_connections", {"endpoint": endpoint}) or 0.0


def _closed_total(endpoint: str, outcome: str) -> float:
    return (
        REGISTRY.get_sample_value("posthog_sse_stream_closed_total", {"endpoint": endpoint, "outcome": outcome}) or 0.0
    )


class TestSSEStreamMetrics:
    # If the gauge ever fails to decrement on an exit path, it reads permanently
    # inflated — and anything keyed on it (dashboards, connection-based
    # autoscaling) sees phantom load. These tests pin every exit path.

    def test_sync_stream_counts_open_and_completed(self):
        response = sse_streaming_response(_gen(), endpoint="test_sync_complete")
        assert b"".join(_sync_content(response)) == b"data: hello\n\n"
        assert _open_connections("test_sync_complete") == 0.0
        assert _closed_total("test_sync_complete", "completed") == 1.0

    def test_sync_stream_error_decrements_gauge_and_counts_error(self):
        def boom() -> Iterator[bytes]:
            yield b"data: one\n\n"
            raise RuntimeError("stream died")

        response = sse_streaming_response(boom(), endpoint="test_sync_error")
        it = _sync_content(response)
        next(it)
        try:
            next(it)
        except RuntimeError:
            pass
        assert _open_connections("test_sync_error") == 0.0
        assert _closed_total("test_sync_error", "error") == 1.0

    def test_sync_stream_early_close_counts_client_disconnect(self):
        def endless() -> Iterator[bytes]:
            while True:
                yield b": ping\n\n"

        response = sse_streaming_response(endless(), endpoint="test_sync_disconnect")
        it = _sync_content(response)
        next(it)
        assert _open_connections("test_sync_disconnect") == 1.0
        response.close()  # what Django does when the client goes away
        assert _open_connections("test_sync_disconnect") == 0.0
        assert _closed_total("test_sync_disconnect", "client_disconnect") == 1.0

    async def test_async_stream_counts_open_and_completed(self):
        async def agen():
            yield b"data: hello\n\n"

        response = sse_streaming_response(agen(), endpoint="test_async_complete")
        assert [chunk async for chunk in _async_content(response)] == [b"data: hello\n\n"]
        assert _open_connections("test_async_complete") == 0.0
        assert _closed_total("test_async_complete", "completed") == 1.0

    async def test_async_stream_early_close_counts_client_disconnect(self):
        async def endless():
            while True:
                yield b": ping\n\n"

        # Django registers the instrumented iterator itself as the response's
        # resource closer, so closing it directly is the disconnect path — the
        # outer streaming_content wrapper does not propagate aclose() eagerly.
        stream = _instrument_stream(endless(), "test_async_disconnect")
        assert isinstance(stream, AsyncIterator)
        await stream.__anext__()
        assert _open_connections("test_async_disconnect") == 1.0
        await stream.aclose()  # type: ignore[attr-defined]
        assert _open_connections("test_async_disconnect") == 0.0
        assert _closed_total("test_async_disconnect", "client_disconnect") == 1.0


class TestStreamingResponse:
    def test_honors_content_type_and_does_not_inject_sse_headers(self):
        # Non-SSE callers (audio, proxies) rely on the general wrapper passing their
        # content_type through and NOT forcing the SSE-only proxy-buffering header.
        response = streaming_response(_gen(), content_type="audio/mpeg")
        assert response.headers["Content-Type"] == "audio/mpeg"
        assert "X-Accel-Buffering" not in response.headers
        assert response.status_code == HTTPStatus.OK
