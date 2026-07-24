import gc
import asyncio
from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator, Iterator
from http import HTTPStatus
from typing import cast

import pytest
from unittest import mock

from django.http import StreamingHttpResponse
from django.http.response import HttpResponseBase
from django.test import override_settings

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.api import streaming
from posthog.api.streaming import (
    _instrument_stream,
    _try_reserve_stream_slot,
    sse_streaming_response,
    streaming_response,
)


def _gen() -> Iterator[bytes]:
    yield b"data: hello\n\n"


async def _agen() -> AsyncIterator[bytes]:
    yield b"data: hello\n\n"


def _reserve_slot() -> streaming._StreamSlotReservation:
    reservation = _try_reserve_stream_slot()
    assert reservation is not None
    return reservation


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


def _sync_content(response: HttpResponseBase) -> Iterator[bytes]:
    # sse_streaming_response returns a union (it can 503); in these non-capped
    # tests the response is always a stream, so narrow and cast.
    assert isinstance(response, StreamingHttpResponse)
    return cast(Iterator[bytes], response.streaming_content)


def _async_content(response: HttpResponseBase) -> AsyncIterator[bytes]:
    assert isinstance(response, StreamingHttpResponse)
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

        # An abandoned async stream is aclosed by the event loop's async
        # generator finalizer, not by response.close() (Django's resource
        # closers are sync-only); drive that aclose() path directly. This is
        # the only release on that path, so pin the slot count too, not just
        # the metrics (baseline-relative: this test runs outside the
        # slot-isolation fixture).
        baseline = streaming._active_stream_count
        stream = _instrument_stream(endless(), "test_async_disconnect", _reserve_slot())
        assert isinstance(stream, AsyncIterable)
        inner = cast(AsyncGenerator[bytes], aiter(stream))
        await inner.__anext__()
        assert _open_connections("test_async_disconnect") == 1.0
        await inner.aclose()
        assert _open_connections("test_async_disconnect") == 0.0
        assert _closed_total("test_async_disconnect", "client_disconnect") == 1.0
        assert streaming._active_stream_count == baseline


class TestStreamingResponse:
    def test_honors_content_type_and_does_not_inject_sse_headers(self):
        # Non-SSE callers (audio, proxies) rely on the general wrapper passing their
        # content_type through and NOT forcing the SSE-only proxy-buffering header.
        response = streaming_response(_gen(), content_type="audio/mpeg")
        assert response.headers["Content-Type"] == "audio/mpeg"
        assert "X-Accel-Buffering" not in response.headers
        assert response.status_code == HTTPStatus.OK


class TestSSEAsyncCancellation:
    async def test_task_cancellation_counts_client_disconnect_not_error(self):
        first_chunk_pulled = asyncio.Event()

        async def blocking():
            yield b": ping\n\n"
            await asyncio.Event().wait()  # park forever; cancellation lands here

        # ASGI cancellation is a path where response.close() never runs, so the
        # generator's finally is the only thing releasing the cap slot; pin it
        # (baseline-relative: this test runs outside the slot-isolation fixture).
        baseline = streaming._active_stream_count
        stream = _instrument_stream(blocking(), "test_async_cancel", _reserve_slot())
        assert isinstance(stream, AsyncIterable)

        async def consume():
            async for _ in stream:
                first_chunk_pulled.set()

        task = asyncio.ensure_future(consume())
        await first_chunk_pulled.wait()
        assert _open_connections("test_async_cancel") == 1.0
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert _open_connections("test_async_cancel") == 0.0
        assert _closed_total("test_async_cancel", "client_disconnect") == 1.0
        assert _closed_total("test_async_cancel", "error") == 0.0
        assert streaming._active_stream_count == baseline


class TestSSEConcurrencyCap:
    # Admission control is the guard against stream pile-up taking a process
    # down; these tests pin the reject/admit boundary and that every afterlife
    # of an admitted response releases its slot exactly once.

    @pytest.fixture(autouse=True)
    def _isolated_slot_count(self):
        # The count is module-global: give each test a zero baseline and put
        # the previous value back so a leak here cannot cascade into other tests.
        with mock.patch.object(streaming, "_active_stream_count", 0):
            yield

    def test_over_cap_rejects_with_503_and_jittered_retry_after(self):
        # The slot is reserved at admission, before any iterator is pulled:
        # two requests admitted back to back must not both pass the cap check.
        with override_settings(SSE_MAX_CONCURRENT_STREAMS_PER_PROCESS=1):
            admitted = sse_streaming_response(_gen(), endpoint="test_cap")
            assert isinstance(admitted, StreamingHttpResponse)
            try:
                rejected = sse_streaming_response(_gen(), endpoint="test_cap")
                assert rejected.status_code == HTTPStatus.SERVICE_UNAVAILABLE
                assert not isinstance(rejected, StreamingHttpResponse)
                assert 15 <= int(rejected.headers["Retry-After"]) < 45
                # A rejection holds no slot, so it must not touch the count.
                assert streaming._active_stream_count == 1
            finally:
                # Always release the slot: a failed assertion must not leak the
                # active-stream count into other tests.
                admitted.close()
            assert streaming._active_stream_count == 0

    def test_capacity_frees_up_when_a_stream_closes(self):
        def endless() -> Iterator[bytes]:
            while True:
                yield b": ping\n\n"

        with override_settings(SSE_MAX_CONCURRENT_STREAMS_PER_PROCESS=1):
            first = sse_streaming_response(endless(), endpoint="test_cap_release")
            assert isinstance(first, StreamingHttpResponse)
            next(_sync_content(first))
            first.close()
            second = sse_streaming_response(_gen(), endpoint="test_cap_release")
            assert isinstance(second, StreamingHttpResponse)
            assert b"".join(_sync_content(second)) == b"data: hello\n\n"

    @parameterized.expand([("sync", _gen), ("async", _agen)])
    def test_closing_a_never_consumed_response_releases_the_slot(self, _name, make_stream):
        # Closing a never-started generator skips its finally, so this release
        # rides on the response's resource closer; if that wiring breaks,
        # every response abandoned before its first chunk leaks capacity.
        with override_settings(SSE_MAX_CONCURRENT_STREAMS_PER_PROCESS=1):
            first = sse_streaming_response(make_stream(), endpoint="test_cap_unconsumed")
            assert isinstance(first, StreamingHttpResponse)
            assert streaming._active_stream_count == 1
            first.close()
            assert streaming._active_stream_count == 0
            second = sse_streaming_response(_gen(), endpoint="test_cap_unconsumed")
            assert isinstance(second, StreamingHttpResponse)
            second.close()

    @parameterized.expand([("sync", _gen), ("async", _agen)])
    def test_dropped_response_releases_the_slot_via_gc(self, _name, make_stream):
        # Django can drop a streaming response without ever calling close():
        # the ASGI handler skips it when the client disconnects during the
        # response-middleware phase, and exception-converting middleware swaps
        # in a 500 and abandons the original. Each occurrence must not consume
        # a slot until the process restarts.
        with override_settings(SSE_MAX_CONCURRENT_STREAMS_PER_PROCESS=1):
            response = sse_streaming_response(make_stream(), endpoint="test_cap_gc")
            assert isinstance(response, StreamingHttpResponse)
            del response
            gc.collect()
            assert streaming._active_stream_count == 0
            readmitted = sse_streaming_response(_gen(), endpoint="test_cap_gc")
            assert isinstance(readmitted, StreamingHttpResponse)
            readmitted.close()

    def test_slot_deferred_under_lock_contention_is_reclaimed_at_next_admission(self):
        # GC can finalize a dropped reservation on a thread that already holds
        # the cap lock, where __del__ must defer instead of block; the slot is
        # then reclaimed by the drain at the next admission. If the deferral or
        # the drain breaks, each such finalization permanently shrinks the cap
        # until the process restarts.
        with override_settings(SSE_MAX_CONCURRENT_STREAMS_PER_PROCESS=1):
            response = sse_streaming_response(_gen(), endpoint="test_cap_deferred")
            assert isinstance(response, StreamingHttpResponse)
            streaming._stream_cap_lock.acquire()
            try:
                del response
                gc.collect()
                # The lock was contended, so the slot cannot be freed yet.
                assert streaming._active_stream_count == 1
            finally:
                streaming._stream_cap_lock.release()
            readmitted = sse_streaming_response(_gen(), endpoint="test_cap_deferred")
            assert isinstance(readmitted, StreamingHttpResponse)
            readmitted.close()
            assert streaming._active_stream_count == 0

    def test_slot_released_when_building_the_response_fails(self):
        # An exception between reserving the slot and returning the response
        # (here: a DB error while releasing request connections) must release
        # eagerly, not wait for GC. Keeping the traceback alive holds the
        # reservation alive, so this catches a dropped except-and-release.
        with override_settings(SSE_MAX_CONCURRENT_STREAMS_PER_PROCESS=1):
            with mock.patch("posthog.api.streaming.connections") as connections:
                connections.all.side_effect = RuntimeError("db went away")
                with pytest.raises(RuntimeError) as excinfo:
                    sse_streaming_response(_gen(), endpoint="test_cap_build_error")
            assert streaming._active_stream_count == 0
            del excinfo

    def test_consumed_then_closed_response_releases_only_once(self):
        # A double release would drive the count negative and let the cap
        # admit unbounded streams.
        with override_settings(SSE_MAX_CONCURRENT_STREAMS_PER_PROCESS=1):
            response = sse_streaming_response(_gen(), endpoint="test_cap_once")
            assert isinstance(response, StreamingHttpResponse)
            assert b"".join(_sync_content(response)) == b"data: hello\n\n"
            assert streaming._active_stream_count == 0
            response.close()
            assert streaming._active_stream_count == 0

    def test_cap_of_zero_rejects_everything(self):
        with override_settings(SSE_MAX_CONCURRENT_STREAMS_PER_PROCESS=0):
            rejected = sse_streaming_response(_gen(), endpoint="test_cap_zero")
            assert rejected.status_code == HTTPStatus.SERVICE_UNAVAILABLE
            rejected_count = REGISTRY.get_sample_value(
                "posthog_sse_rejected_over_cap_total", {"endpoint": "test_cap_zero"}
            )
            assert rejected_count is not None and rejected_count >= 1.0
