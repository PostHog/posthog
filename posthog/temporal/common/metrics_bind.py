import errno
import asyncio
import collections.abc
from typing import TypeVar

from posthog.temporal.common.logger import get_write_only_logger

logger = get_write_only_logger(__name__)

# A previously running worker may still hold the metrics port for a short window during a
# rolling restart. Retry with linear backoff to give it time to release the port before
# failing with an actionable error.
BIND_MAX_ATTEMPTS = 5
BIND_BACKOFF_SECONDS = 1.0

T = TypeVar("T")


def is_address_in_use_error(exc: BaseException) -> bool:
    """Return True if the exception represents an "address already in use" (EADDRINUSE) failure.

    Covers both Python's ``OSError`` (raised by asyncio/aiohttp when binding a TCP site) and the
    Temporal SDK's runtime, which surfaces the same condition from its Rust core as a generic
    exception whose message mentions the address being in use.
    """
    if isinstance(exc, OSError) and exc.errno == errno.EADDRINUSE:
        return True
    return "address already in use" in str(exc).lower()


async def bind_with_retry(
    bind: collections.abc.Callable[[], collections.abc.Awaitable[T] | T],
    *,
    port: int,
    description: str,
) -> T:
    """Run a port-binding callable, retrying on EADDRINUSE with linear backoff.

    ``bind`` may return either a value or an awaitable (so it works for both the synchronous
    Temporal SDK runtime bind and aiohttp's coroutine-based ``TCPSite.start``). If the port is
    still in use after all attempts, raises an ``OSError`` with an actionable message naming the
    conflicting port instead of letting a bare ``OSError 98`` crash worker startup.
    """
    last_error: BaseException | None = None
    for attempt in range(1, BIND_MAX_ATTEMPTS + 1):
        try:
            result = bind()
            if isinstance(result, collections.abc.Awaitable):
                return await result
            return result
        except Exception as e:
            if not is_address_in_use_error(e):
                raise
            last_error = e
            if attempt < BIND_MAX_ATTEMPTS:
                logger.warning(
                    "metrics_bind.port_in_use_retrying",
                    description=description,
                    port=port,
                    attempt=attempt,
                    max_attempts=BIND_MAX_ATTEMPTS,
                )
                await asyncio.sleep(BIND_BACKOFF_SECONDS * attempt)

    raise OSError(
        errno.EADDRINUSE,
        f"{description} could not bind to port {port} after {BIND_MAX_ATTEMPTS} attempts: the port "
        f"is still in use. Another worker process may still hold it (e.g. during a rolling restart), "
        f"or two workers on this host are configured with the same metrics port "
        f"(PROMETHEUS_METRICS_EXPORT_PORT={port}).",
    ) from last_error
