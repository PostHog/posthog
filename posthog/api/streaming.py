from collections.abc import AsyncIterable, Iterable
from http import HTTPStatus

from django.db import connections
from django.http import StreamingHttpResponse

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
    """
    return streaming_response(
        stream,
        content_type="text/event-stream",
        status=status,
        headers={**_SSE_DEFAULT_HEADERS, **(headers or {})},
    )
