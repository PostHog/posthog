"""Classify transient Gemini failures so Temporal retries them with a longer backoff.

Gemini's REST API surfaces a wide mix of transient signals — 503 UNAVAILABLE / "high
demand", 504 from the egress proxy, deadline-expired, mid-response TLS resets,
truncated chunked transfers, and even SSL context construction blowing up while loading
the worker's PEM bundle. Without classification these bubble up as bare ``Exception``s
and Temporal retries them with the default backoff, which is too tight for the segment
fan-out to ride through Gemini blips.

Use :func:`raise_retryable_for_transient_gemini_error` from inside an ``except`` block
around Gemini client construction and request calls; it re-raises retryable failures as
:class:`temporalio.exceptions.ApplicationError` with a long ``next_retry_delay`` and
lets non-transient failures propagate untouched.
"""

import ssl
from datetime import timedelta

import httpx
import aiohttp
from google.genai import errors as genai_errors
from temporalio.exceptions import ApplicationError

# Retry classification covers transient Gemini failures: capacity (503 / 'high demand'),
# upstream gateway timeouts (504), deadline-exceeded responses, and connection-level
# resets from the egress proxy or the underlying httpx/aiohttp clients.
_RETRYABLE_NETWORK_EXCEPTIONS: tuple[type[BaseException], ...] = (
    # httpx (sync upload path)
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.ProxyError,
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.PoolTimeout,
    # aiohttp (async generate_content path)
    aiohttp.ClientOSError,
    aiohttp.ClientConnectorError,
    aiohttp.ClientPayloadError,
    aiohttp.ServerDisconnectedError,
    aiohttp.ServerTimeoutError,
    aiohttp.ClientHttpProxyError,
    aiohttp.ClientResponseError,
    # OS-level connection failures that surface raw from underlying sockets
    ConnectionResetError,
    BrokenPipeError,
    # SSL handshake / cert load failures (e.g. SSLError [X509] PEM lib during client init)
    ssl.SSLError,
)


def _is_retryable_genai_error(exc: genai_errors.APIError) -> bool:
    """Server-side Gemini errors are retryable; client errors (4xx) generally are not.

    ``ServerError`` covers 5xx (including 503 UNAVAILABLE and 504 gateway timeout). We
    also retry on the well-known transient ``ClientError`` shapes: 408 (request timeout)
    and 429 (resource exhausted / rate limited) — the segment fan-out is bursty enough
    that brief 429s are routinely transient.
    """
    if isinstance(exc, genai_errors.ServerError):
        return True
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in (408, 429, 500, 502, 503, 504):
        return True
    message = (str(exc) or "").lower()
    return any(
        token in message
        for token in (
            "unavailable",
            "deadline",
            "high demand",
            "failed to convert server response to json",
            "gateway timeout",
        )
    )


def raise_retryable_for_transient_gemini_error(
    exc: BaseException,
    *,
    context: str,
    next_retry_delay: timedelta = timedelta(seconds=30),
) -> None:
    """Re-raise transient Gemini failures as retryable ``ApplicationError``s.

    If ``exc`` is not classified as transient this is a no-op — the caller's ``raise``
    will propagate the original exception unchanged so non-retryable bugs (auth errors,
    bad inputs, logic mistakes) still surface immediately.

    ``next_retry_delay`` overrides the activity's default exponential backoff for this
    attempt only, giving Gemini time to recover from capacity / proxy hiccups instead
    of hammering it on the standard 2x curve.
    """
    if isinstance(exc, genai_errors.APIError):
        if not _is_retryable_genai_error(exc):
            return
        raise ApplicationError(
            f"transient Gemini error during {context}: {exc!r}",
            type="GeminiTransientError",
            next_retry_delay=next_retry_delay,
        ) from exc
    if isinstance(exc, _RETRYABLE_NETWORK_EXCEPTIONS):
        raise ApplicationError(
            f"transient network error during {context}: {exc!r}",
            type="GeminiTransientError",
            next_retry_delay=next_retry_delay,
        ) from exc
