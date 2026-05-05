import random
import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

_T = TypeVar("_T")


async def run_parallel_with_backoff(
    fns: list[Callable[[], Awaitable[_T]]],
    *,
    concurrency: int = 10,
    max_attempts: int = 5,
    base_delay_seconds: float = 1.0,
    max_delay_seconds: float = 30.0,
    is_retryable: Callable[[BaseException], bool] = lambda _exc: False,
    get_retry_delay: Callable[[BaseException], float | None] = lambda _exc: None,
) -> list[_T | BaseException]:
    """Run zero-arg async callables with bounded concurrency and exponential backoff.

    Each callable runs under a shared :class:`asyncio.Semaphore` of size ``concurrency``.
    On exception, the wrapper consults ``is_retryable``: if true, it sleeps for
    ``get_retry_delay(exc)`` (falling back to exponential backoff with 20% jitter)
    and retries up to ``max_attempts`` times. Non-retryable exceptions are returned
    in-place in the result list, preserving input order.

    Generic over the retry policy so it can be used with any client whose errors
    carry retry hints (rate limits, 429/503 with Retry-After, etc.).
    """
    if not fns:
        return []
    semaphore = asyncio.Semaphore(concurrency)

    async def run_one(fn: Callable[[], Awaitable[_T]]) -> _T | BaseException:
        async with semaphore:
            last_exc: BaseException | None = None
            for attempt in range(max_attempts):
                try:
                    return await fn()
                except Exception as exc:
                    last_exc = exc
                    if not is_retryable(exc) or attempt == max_attempts - 1:
                        return exc
                    delay = get_retry_delay(exc)
                    if delay is None:
                        delay = min(base_delay_seconds * (2**attempt), max_delay_seconds)
                    delay = delay + random.uniform(0, delay * 0.2)
                    await asyncio.sleep(delay)
            assert last_exc is not None
            return last_exc

    return await asyncio.gather(*(run_one(fn) for fn in fns), return_exceptions=False)
