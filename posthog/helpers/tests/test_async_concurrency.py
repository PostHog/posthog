import asyncio

from posthog.helpers.async_concurrency import run_parallel_with_backoff


class _RetryableError(Exception):
    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, _RetryableError)


def _delay_for(exc: BaseException) -> float | None:
    return getattr(exc, "retry_after_seconds", None)


def test_retries_when_predicate_returns_true():
    attempts: list[int] = []

    async def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise _RetryableError("rate limited", retry_after_seconds=0.01)
        return "ok"

    result = asyncio.run(run_parallel_with_backoff([flaky], is_retryable=_is_retryable, get_retry_delay=_delay_for))
    assert result == ["ok"]
    assert len(attempts) == 3


def test_does_not_retry_when_predicate_returns_false():
    attempts: list[int] = []

    async def broken():
        attempts.append(1)
        raise ValueError("terminal")

    result = asyncio.run(run_parallel_with_backoff([broken], is_retryable=_is_retryable, get_retry_delay=_delay_for))
    assert len(result) == 1
    assert isinstance(result[0], ValueError)
    assert len(attempts) == 1


def test_gives_up_after_max_attempts():
    attempts: list[int] = []

    async def always_rate_limited():
        attempts.append(1)
        raise _RetryableError("always", retry_after_seconds=0.001)

    result = asyncio.run(
        run_parallel_with_backoff(
            [always_rate_limited],
            max_attempts=3,
            is_retryable=_is_retryable,
            get_retry_delay=_delay_for,
        )
    )
    assert len(result) == 1
    assert isinstance(result[0], _RetryableError)
    assert len(attempts) == 3


def test_empty_input_returns_empty():
    assert asyncio.run(run_parallel_with_backoff([])) == []


def test_respects_concurrency_cap():
    in_flight = 0
    observed: list[int] = []
    lock = asyncio.Lock()

    async def task():
        nonlocal in_flight
        async with lock:
            in_flight += 1
            observed.append(in_flight)
        await asyncio.sleep(0.01)
        async with lock:
            in_flight -= 1
        return None

    asyncio.run(run_parallel_with_backoff([task] * 20, concurrency=3))
    assert max(observed) <= 3
