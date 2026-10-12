import time
import random
import asyncio
import threading
from collections import deque
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Callable,
    Generator,
    Iterable,
    Iterator,
)
from http import HTTPStatus

from django.conf import settings
from django.db import connections
from django.http import HttpResponse, StreamingHttpResponse

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


SSE_REJECTED_OVER_CAP_COUNTER = Counter(
    "posthog_sse_rejected_over_cap_total",
    "SSE streams rejected with 503 because the per-process concurrency cap was reached",
    labelnames=["endpoint"],
)

# Rejected clients get "come back in base + [0, jitter) seconds" so a burst that
# hits the cap spreads its retries out instead of reconnecting in lockstep.
_RETRY_AFTER_BASE_SECONDS = 15
_RETRY_AFTER_JITTER_SECONDS = 30


def _record_stream_open(endpoint: str) -> None:
    SSE_STREAM_OPENED_COUNTER.labels(endpoint=endpoint).inc()
    SSE_OPEN_CONNECTIONS_GAUGE.labels(endpoint=endpoint).inc()


def _record_stream_close(endpoint: str, outcome: str, started_at: float) -> None:
    SSE_OPEN_CONNECTIONS_GAUGE.labels(endpoint=endpoint).dec()
    SSE_STREAM_CLOSED_COUNTER.labels(endpoint=endpoint, outcome=outcome).inc()
    SSE_STREAM_DURATION_HISTOGRAM.labels(endpoint=endpoint).observe(time.monotonic() - started_at)


class _StreamSlotReservation:
    """One admitted slot against a per-process stream budget.

    ``release`` is idempotent: both afterlives of a response call it (the
    instrumented iterator's ``finally`` when the stream ran, the response's
    resource closer when it never did) and only the first call frees the slot.
    ``__del__`` backstops responses dropped without ``close()`` at all (the
    ASGI handler skips it when the client disconnects during the
    response-middleware phase, and exception-converting middleware drops the
    original response unclosed), which would otherwise leak the slot until the
    process restarts.
    """

    __slots__ = ("_budget", "_released")

    def __init__(self, budget: "StreamBudget") -> None:
        self._budget = budget
        self._released = False

    def release(self) -> None:
        budget = self._budget
        with budget.lock:
            if self._released:
                return
            self._released = True
            budget.active_count -= 1

    def __del__(self) -> None:
        # GC can run while this thread holds the cap lock, so never block on it
        # here: decrement inline when the lock is free, otherwise defer to the
        # queue the next admission drains. No lock guards the flag because an
        # object being finalized has no other referents left to race with.
        if self._released:
            return
        budget = self._budget
        if budget.lock.acquire(blocking=False):
            try:
                self._released = True
                budget.active_count -= 1
            finally:
                budget.lock.release()
        else:
            self._released = True
            budget.deferred_releases.append(None)


class StreamBudget:
    """A per-process cap on concurrent SSE streams, read from the setting ``cap_setting``.

    Every SSE endpoint shares one default budget. An endpoint whose streams are
    idle for most of their life and open in every foreground tab passes its own
    budget to ``sse_streaming_response``, so that those streams cannot use up the
    slots that interactive streams need.
    """

    def __init__(self, cap_setting: str) -> None:
        self._cap_setting = cap_setting
        # Count of admitted streams: a slot is reserved under the lock before the
        # response leaves the view and released exactly once per stream, so
        # parallel admissions cannot race past the cap. The lock guards only the
        # check-and-increment and the release, never a yield or await. This
        # counts reservations; the module gauge and counters keep counting streams
        # that actually started being consumed.
        self.lock = threading.Lock()
        self.active_count = 0
        # Slots freed by the GC backstop while the lock was unavailable.
        # ``__del__`` can fire at any allocation point, including on a thread that
        # already holds the non-reentrant lock, so it must never block on it;
        # ``deque.append`` is atomic, and admission drains this queue under the lock.
        self.deferred_releases: deque[None] = deque()

    def try_reserve(self) -> _StreamSlotReservation | None:
        cap = getattr(settings, self._cap_setting)
        with self.lock:
            while self.deferred_releases:
                self.deferred_releases.popleft()
                self.active_count -= 1
            if cap is not None and self.active_count >= cap:
                return None
            self.active_count += 1
        return _StreamSlotReservation(self)


_SHARED_STREAM_BUDGET = StreamBudget("SSE_MAX_CONCURRENT_STREAMS_PER_PROCESS")


def _stream_cap_rejection(endpoint: str) -> HttpResponse:
    SSE_REJECTED_OVER_CAP_COUNTER.labels(endpoint=endpoint).inc()
    retry_after = _RETRY_AFTER_BASE_SECONDS + random.randrange(_RETRY_AFTER_JITTER_SECONDS)
    return HttpResponse(
        status=HTTPStatus.SERVICE_UNAVAILABLE,
        headers={"Retry-After": str(retry_after), **_SSE_DEFAULT_HEADERS},
    )


async def _instrumented_aiter(
    stream: AsyncIterable[bytes | str], endpoint: str, reservation: _StreamSlotReservation
) -> AsyncGenerator[bytes | str]:
    """Pass chunks through untouched, tracking the open gauge, outcome, and duration.

    Metric work happens only at stream start and end — nothing is added per
    chunk. A client disconnect surfaces here as cancellation of the generator
    (``GeneratorExit`` from ``aclose()``, or ``asyncio.CancelledError`` when the
    ASGI handler cancels the streaming task), which is why both get their own
    outcome rather than folding into ``error``.
    """
    _record_stream_open(endpoint)
    started_at = time.monotonic()
    outcome = "completed"
    iterator: AsyncIterator[bytes | str] | None = None
    try:
        iterator = aiter(stream)
        async for chunk in iterator:
            yield chunk
    except (GeneratorExit, asyncio.CancelledError):
        outcome = "client_disconnect"
        raise
    except BaseException:
        outcome = "error"
        raise
    finally:
        try:
            close = getattr(iterator, "aclose", None)
            if close is not None:
                await close()
        finally:
            _record_stream_close(endpoint, outcome, started_at)
            reservation.release()


def _instrumented_iter(
    stream: Iterable[bytes | str], endpoint: str, reservation: _StreamSlotReservation
) -> Generator[bytes | str]:
    _record_stream_open(endpoint)
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
        reservation.release()


class _ReservedSyncStream:
    """Ties the cap reservation to response cleanup for a sync stream.

    ``StreamingHttpResponse`` registers ``close`` as a resource closer, which
    runs whenever Django closes the response (WSGI servers per spec, the ASGI
    handler on the normal path). Closing a generator whose body never started
    skips its ``finally``, so this wrapper, not the generator, is what releases
    the slot for a never-consumed response. Responses Django drops without
    calling ``close()`` at all fall through to the reservation's ``__del__``.
    """

    def __init__(self, iterator: Generator[bytes | str], reservation: _StreamSlotReservation) -> None:
        self._iterator = iterator
        self._reservation = reservation

    def __iter__(self) -> Iterator[bytes | str]:
        return self._iterator

    def close(self) -> None:
        self._iterator.close()
        self._reservation.release()


class _ReservedAsyncStream:
    """Async counterpart of ``_ReservedSyncStream``.

    Deliberately has no ``__iter__`` so ``StreamingHttpResponse`` takes its
    async path. The closer stays sync because Django invokes resource closers
    synchronously; it cannot unwind a started async generator, but a started
    generator already releases in its ``finally`` (the ASGI handler cancels it
    on disconnect, the event loop finalizer closes it if abandoned), so only
    the never-started case needs covering here.
    """

    def __init__(self, aiterator: AsyncGenerator[bytes | str], reservation: _StreamSlotReservation) -> None:
        self._aiterator = aiterator
        self._reservation = reservation

    def __aiter__(self) -> AsyncIterator[bytes | str]:
        return self._aiterator

    def close(self) -> None:
        self._reservation.release()


def _instrument_stream(stream: StreamContent, endpoint: str, reservation: _StreamSlotReservation) -> StreamContent:
    if isinstance(stream, AsyncIterable):
        return _ReservedAsyncStream(_instrumented_aiter(stream, endpoint, reservation), reservation)
    return _ReservedSyncStream(_instrumented_iter(stream, endpoint, reservation), reservation)


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
    budget: StreamBudget | None = None,
) -> StreamingHttpResponse | HttpResponse:
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

    Admission control: when this process is already serving
    ``SSE_MAX_CONCURRENT_STREAMS_PER_PROCESS`` streams (or the cap of the
    ``budget`` the caller passes), the stream is not opened and the client gets
    ``503`` with a jittered ``Retry-After``. Beware that a native
    ``EventSource`` treats any non-200 response as fatal (readyState CLOSED, no
    auto-reconnect) and ignores ``Retry-After``; the jittered header only
    spreads out clients that retry at the HTTP layer, so ``EventSource``
    consumers must schedule their own reconnect from ``onerror`` to recover
    from a rejection. A slot is reserved atomically before the response is
    returned, so parallel admissions cannot overshoot the cap; the slot is
    released when the stream ends, when a never-consumed response is closed,
    or by a GC backstop when the response is dropped without being closed.
    """
    reservation = (budget or _SHARED_STREAM_BUDGET).try_reserve()
    if reservation is None:
        return _stream_cap_rejection(endpoint)
    try:
        return streaming_response(
            _instrument_stream(stream, endpoint, reservation),
            content_type="text/event-stream",
            status=status,
            headers={**_SSE_DEFAULT_HEADERS, **(headers or {})},
        )
    except BaseException:
        # Nothing owns the slot until the response exists: a failure here (a DB
        # error while releasing connections, a bad caller-supplied header) must
        # not strand the reservation until GC gets to it.
        reservation.release()
        raise


SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0


async def sse_rotating_event_stream(
    receive: Callable[[float], Awaitable[bytes | None]],
    *,
    max_duration_seconds: float,
    heartbeat_interval_seconds: float = SSE_HEARTBEAT_INTERVAL_SECONDS,
) -> AsyncGenerator[bytes]:
    """Send each payload from ``receive`` as a ``data`` frame until ``max_duration_seconds`` pass, then ``end``.

    ``receive(timeout)`` waits up to ``timeout`` seconds for the next payload and
    returns None when the time runs out. The loop passes the time left until the
    next heartbeat or the deadline, so an idle stream wakes once per heartbeat
    instead of once per poll. A ``: heartbeat`` comment goes out when no frame went
    out for ``heartbeat_interval_seconds``, so proxies keep the connection open.

    The client reconnects when it reads ``end``. The rotation spreads streams over
    processes again after a deploy and limits how long one stream holds a slot.
    """
    started_at = time.monotonic()
    last_write = started_at
    while (elapsed := time.monotonic() - started_at) < max_duration_seconds:
        idle = time.monotonic() - last_write
        if idle >= heartbeat_interval_seconds:
            yield b": heartbeat\n\n"
            last_write = time.monotonic()
            continue
        payload = await receive(min(max_duration_seconds - elapsed, heartbeat_interval_seconds - idle))
        if payload is not None:
            yield b"data: " + payload + b"\n\n"
            last_write = time.monotonic()
    yield b"event: end\ndata: reconnect\n\n"
