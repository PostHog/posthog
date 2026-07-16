import time
import random
import asyncio
import threading
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator, Generator, Iterable, Iterator
from http import HTTPStatus

from django.conf import settings
from django.db import connections
from django.http import HttpResponse, StreamingHttpResponse

import posthoganalytics
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

# Per-process count of admitted streams: a slot is reserved under the lock
# before the response leaves the view and released exactly once per stream,
# so parallel admissions cannot race past the cap. The lock guards only the
# check-and-increment and the release, never a yield or await. This counts
# reservations; the gauge and counters above keep counting streams that
# actually started being consumed.
_stream_cap_lock = threading.Lock()
_active_stream_count = 0

# Slots freed by the GC backstop while the cap lock was unavailable. ``__del__``
# can fire at any allocation point, including on a thread that already holds the
# non-reentrant lock, so it must never block on it; ``deque.append`` is atomic,
# and admission drains this queue under the lock.
_deferred_slot_releases: deque[None] = deque()

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


SSE_KILLSWITCH_REJECTED_COUNTER = Counter(
    "posthog_sse_killswitch_rejected_total",
    "SSE streams answered with 204 because the endpoint's killswitch flag is on",
    labelnames=["endpoint"],
)


def _killswitch_enabled(flag: str, distinct_id: str) -> bool:
    """Evaluate an SSE killswitch flag locally, failing open.

    Local-only evaluation: no per-request decide call on a hot endpoint (flag
    definitions are served via HyperCache). Killswitches are meant to be
    all-or-nothing flags, so the distinct_id rarely matters; it is accepted so
    endpoints can pass their user for partial rollouts of a kill.
    """
    try:
        return bool(
            posthoganalytics.feature_enabled(
                flag,
                distinct_id,
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False


def sse_killswitch_rejection(
    endpoint: str,
    flag: str,
    distinct_id: str = "sse-killswitch",
) -> HttpResponse | None:
    """Return the killswitch 204 when ``flag`` is on, else ``None``.

    ``sse_streaming_response`` already applies the killswitch, but only at
    response-construction time. Views that do side-effecting work before
    building their stream (launching a workflow, invoking an upstream service)
    must call this first, or a kill only discards the response while the work
    keeps happening on every reconnect.
    """
    if _killswitch_enabled(flag, distinct_id):
        SSE_KILLSWITCH_REJECTED_COUNTER.labels(endpoint=endpoint).inc()
        return HttpResponse(status=HTTPStatus.NO_CONTENT)
    return None


class _StreamSlotReservation:
    """One admitted slot against the per-process stream cap.

    ``release`` is idempotent: both afterlives of a response call it (the
    instrumented iterator's ``finally`` when the stream ran, the response's
    resource closer when it never did) and only the first call frees the slot.
    ``__del__`` backstops responses dropped without ``close()`` at all (the
    ASGI handler skips it when the client disconnects during the
    response-middleware phase, and exception-converting middleware drops the
    original response unclosed), which would otherwise leak the slot until the
    process restarts.
    """

    __slots__ = ("_released",)

    def __init__(self) -> None:
        self._released = False

    def release(self) -> None:
        global _active_stream_count
        with _stream_cap_lock:
            if self._released:
                return
            self._released = True
            _active_stream_count -= 1

    def __del__(self) -> None:
        # GC can run while this thread holds the cap lock, so never block on it
        # here: decrement inline when the lock is free, otherwise defer to the
        # queue the next admission drains. No lock guards the flag because an
        # object being finalized has no other referents left to race with.
        global _active_stream_count
        if self._released:
            return
        if _stream_cap_lock.acquire(blocking=False):
            try:
                self._released = True
                _active_stream_count -= 1
            finally:
                _stream_cap_lock.release()
        else:
            self._released = True
            _deferred_slot_releases.append(None)


def _try_reserve_stream_slot() -> _StreamSlotReservation | None:
    global _active_stream_count
    cap = settings.SSE_MAX_CONCURRENT_STREAMS_PER_PROCESS
    with _stream_cap_lock:
        while _deferred_slot_releases:
            _deferred_slot_releases.popleft()
            _active_stream_count -= 1
        if cap is not None and _active_stream_count >= cap:
            return None
        _active_stream_count += 1
    return _StreamSlotReservation()


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
    killswitch_flag: str | None = None,
    killswitch_distinct_id: str = "sse-killswitch",
    status: int = HTTPStatus.OK,
    headers: dict[str, str] | None = None,
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
    ``SSE_MAX_CONCURRENT_STREAMS_PER_PROCESS`` streams, the stream is not opened
    and the client gets ``503`` with a jittered ``Retry-After``. Beware that a
    native ``EventSource`` treats any non-200 response as fatal (readyState
    CLOSED, no auto-reconnect) and ignores ``Retry-After``; the jittered header
    only spreads out clients that retry at the HTTP layer, so ``EventSource``
    consumers must schedule their own reconnect from ``onerror`` to recover
    from a rejection. A slot is reserved atomically before the response is
    returned, so parallel admissions cannot overshoot the cap; the slot is
    released when the stream ends, when a never-consumed response is closed,
    or by a GC backstop when the response is dropped without being closed.

    Killswitch: when ``killswitch_flag`` names a feature flag that evaluates
    true, the stream is answered with ``204 No Content`` before any other work,
    without reserving a cap slot. Per the SSE spec, 204 moves ``EventSource``
    to ``CLOSED`` and it stops reconnecting, the only server-side signal that
    reaches clients whose tabs are already open. A client-side flag cannot do
    this: it is read at render time and open tabs never re-check it.
    Killswitch flags follow the ``<product>-sse-killswitch`` naming convention
    and fail open if evaluation errors.
    """
    if killswitch_flag is not None:
        rejection = sse_killswitch_rejection(endpoint, killswitch_flag, killswitch_distinct_id)
        if rejection is not None:
            return rejection
    reservation = _try_reserve_stream_slot()
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
