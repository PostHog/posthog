import time
import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
from http import HTTPStatus

from django.db import connections
from django.http import StreamingHttpResponse

from prometheus_client import Counter, Gauge, Histogram

# What StreamingHttpResponse actually accepts: sync or async iterables of bytes or
# str chunks (Django encodes str via the response charset). Broad on purpose — SSE
# views yield str, proxies yield bytes, and the empty-stream stub passes a list.
StreamContent = Iterable[bytes | str] | AsyncIterable[bytes | str]

# Disable proxy buffering/caching so SSE chunks reach the client immediately
# (nginx/Envoy in front of web-django otherwise buffer the stream).
_SSE_DEFAULT_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}

# The `endpoint` label is a static name passed by each SSE view — never a raw
# request path, which would blow up label cardinality.
SSE_OPEN_CONNECTIONS_GAUGE = Gauge(
    "posthog_open_sse_connections",
    "SSE streams currently being served by this process",
    labelnames=["endpoint"],
    multiprocess_mode="livesum",
)
SSE_STREAM_OPENED_COUNTER = Counter(
    "posthog_sse_stream_opened_total",
    "SSE streams that started being consumed",
    labelnames=["endpoint"],
)
SSE_STREAM_CLOSED_COUNTER = Counter(
    "posthog_sse_stream_closed_total",
    "SSE streams that ended, by outcome",
    labelnames=["endpoint", "outcome"],
)
# Streams legitimately run for many minutes (rotation caps them at ~15 min),
# so buckets extend well past the default 10s ceiling.
SSE_STREAM_DURATION_HISTOGRAM = Histogram(
    "posthog_sse_stream_duration_seconds",
    "Wall-clock lifetime of an SSE stream, from first chunk pulled to close",
    labelnames=["endpoint"],
    buckets=(1, 5, 15, 60, 180, 420, 900, 1200, float("inf")),
)


def _record_stream_close(endpoint: str, outcome: str, started_at: float) -> None:
    SSE_OPEN_CONNECTIONS_GAUGE.labels(endpoint=endpoint).dec()
    SSE_STREAM_CLOSED_COUNTER.labels(endpoint=endpoint, outcome=outcome).inc()
    SSE_STREAM_DURATION_HISTOGRAM.labels(endpoint=endpoint).observe(time.monotonic() - started_at)


async def _instrumented_aiter(stream: AsyncIterable[bytes | str], endpoint: str) -> AsyncIterator[bytes | str]:
    """Pass chunks through untouched, tracking open count, outcome, and duration.

    Metric work happens only at stream start and end — nothing is added per
    chunk. A client disconnect surfaces here as cancellation of the generator
    (``GeneratorExit`` from ``aclose()``, or ``asyncio.CancelledError`` when the
    ASGI handler cancels the streaming task), which is why both get their own
    outcome rather than folding into ``error``.
    """
    SSE_STREAM_OPENED_COUNTER.labels(endpoint=endpoint).inc()
    SSE_OPEN_CONNECTIONS_GAUGE.labels(endpoint=endpoint).inc()
    started_at = time.monotonic()
    outcome = "completed"
    try:
        async for chunk in stream:
            yield chunk
    except (GeneratorExit, asyncio.CancelledError):
        outcome = "client_disconnect"
        raise
    except BaseException:
        outcome = "error"
        raise
    finally:
        _record_stream_close(endpoint, outcome, started_at)


def _instrumented_iter(stream: Iterable[bytes | str], endpoint: str) -> Iterator[bytes | str]:
    SSE_STREAM_OPENED_COUNTER.labels(endpoint=endpoint).inc()
    SSE_OPEN_CONNECTIONS_GAUGE.labels(endpoint=endpoint).inc()
    started_at = time.monotonic()
    outcome = "completed"
    try:
        yield from stream
    except GeneratorExit:
        outcome = "client_disconnect"
        raise
    except BaseException:
        outcome = "error"
        raise
    finally:
        _record_stream_close(endpoint, outcome, started_at)


def _instrument_stream(stream: StreamContent, endpoint: str) -> StreamContent:
    if isinstance(stream, AsyncIterable):
        return _instrumented_aiter(stream, endpoint)
    return _instrumented_iter(stream, endpoint)


def _release_request_connections() -> None:
    """Close this thread's DB connections, unless a transaction is open.

    Closes unconditionally (``conn.close()``) rather than via
    ``close_if_unusable_or_obsolete()``, which only closes connections past their
    ``CONN_MAX_AGE`` — that would make this helper a silent no-op if the setting
    ever became nonzero, re-pinning a pgbouncer slot per stream. Closing an idle
    autocommit connection is always safe; Django reopens on next use.

    Connections inside an atomic block are skipped: severing an open transaction
    corrupts it. PostHog never streams from inside ``transaction.atomic()``, so in
    production this closes everything; the case that does hit the guard is Django
    ``TestCase``'s per-test transaction wrapper, which the test client only shields
    from the signal-dispatched ``close_old_connections``, not from direct calls
    like this one.
    """
    for conn in connections.all(initialized_only=True):
        if not conn.in_atomic_block:
            conn.close()


def streaming_response(
    stream: StreamContent,
    *,
    content_type: str,
    status: int = HTTPStatus.OK,
    headers: dict[str, str] | None = None,
) -> StreamingHttpResponse:
    """Build a ``StreamingHttpResponse``, releasing request-thread DB connections first.

    Use this (or ``sse_streaming_response`` for SSE) instead of constructing
    ``StreamingHttpResponse`` directly — a semgrep rule enforces it. See
    ``sse_streaming_response`` for why releasing connections matters.

    The stream body must not rely on the request-thread connection: do any
    in-stream DB work through ``posthog.sync.database_sync_to_async`` so it
    acquires and releases its own connection.
    """
    _release_request_connections()
    return StreamingHttpResponse(
        stream,
        status=status,
        content_type=content_type,
        headers=headers or {},
    )


def sse_streaming_response(
    stream: StreamContent,
    *,
    endpoint: str = "unknown",
    status: int = HTTPStatus.OK,
    headers: dict[str, str] | None = None,
) -> StreamingHttpResponse:
    """Build a ``text/event-stream`` response for a long-lived SSE endpoint.

    Use this instead of constructing ``StreamingHttpResponse`` directly. It
    enforces the invariant that's otherwise easy to forget:

        sync DB work before a long-lived SSE stream must release its connection
        before streaming starts.

    PostHog runs with ``CONN_MAX_AGE = 0``, so any connection still open when the
    stream begins (from authentication, team resolution, ``get_object``, or
    serializer/ORM reads in the sync view) stays pinned to a pgbouncer client
    slot for the *entire* stream — ``request_finished`` only frees it once the
    stream ends, which for SSE is many minutes. At scale that turns every
    concurrent subscriber into a held connection and exhausts the pool. Releasing
    the request-thread connections here frees them before the stream starts.

    The stream body must not rely on the request-thread connection: do any
    in-stream DB work through ``posthog.sync.database_sync_to_async`` so it
    acquires and releases its own connection.

    Limitation: this runs at view-return time, but response-phase middleware runs
    after the view returns and before the stream body is consumed — middleware
    that touches the DB in ``process_response`` lazily reopens a connection that
    then stays pinned for the whole stream. Keep response middleware DB-free on
    SSE paths.

    ``endpoint`` is a static, low-cardinality name for the stream (e.g.
    ``"wizard_session"``) used as the label on the SSE connection metrics.
    """
    return streaming_response(
        _instrument_stream(stream, endpoint),
        content_type="text/event-stream",
        status=status,
        headers={**_SSE_DEFAULT_HEADERS, **(headers or {})},
    )
