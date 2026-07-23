import pytest
from unittest.mock import AsyncMock, patch

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut

from ee.hogai.context.query_retry import aretry_transient_query, is_transient_query_error, to_max_tool_error
from ee.hogai.tool_errors import MaxToolRetryableError, MaxToolTransientError


class _Counter:
    def __init__(self, fail_times: int, error: Exception):
        self.calls = 0
        self._fail_times = fail_times
        self._error = error

    async def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._error
        return "ok"


async def test_retries_transient_error_then_succeeds():
    thunk = _Counter(fail_times=2, error=ClickHouseAtCapacity())
    with patch("ee.hogai.context.query_retry.asyncio.sleep", new_callable=AsyncMock) as sleep:
        result = await aretry_transient_query(thunk, base_delay_s=0.01)
    assert result == "ok"
    assert thunk.calls == 3  # two capacity failures were retried, third call succeeded
    assert sleep.await_count == 2


async def test_does_not_retry_non_transient_error():
    thunk = _Counter(fail_times=5, error=ValueError("bad input"))
    with patch("ee.hogai.context.query_retry.asyncio.sleep", new_callable=AsyncMock) as sleep:
        with pytest.raises(ValueError):
            await aretry_transient_query(thunk)
    assert thunk.calls == 1  # a non-transient error must surface immediately, not burn retries
    assert sleep.await_count == 0


async def test_reraises_transient_error_after_exhausting_attempts():
    thunk = _Counter(fail_times=99, error=ClickHouseAtCapacity())
    with patch("ee.hogai.context.query_retry.asyncio.sleep", new_callable=AsyncMock) as sleep:
        with pytest.raises(ClickHouseAtCapacity):
            await aretry_transient_query(thunk, max_attempts=3, base_delay_s=0.01)
    assert thunk.calls == 3
    assert sleep.await_count == 2  # slept between the 3 attempts, not after the last


@pytest.mark.parametrize(
    "error,expected_transient",
    [
        (ClickHouseAtCapacity(), True),
        (ClickHouseQueryMemoryLimitExceeded(), True),
        (ConcurrencyLimitExceeded(), True),
        (ClickHouseQueryTimeOut(), False),
        (ValueError("nope"), False),
    ],
)
def test_is_transient_query_error(error, expected_transient):
    assert is_transient_query_error(error) is expected_transient


@pytest.mark.parametrize(
    "error,expected_cls",
    [
        (ClickHouseAtCapacity(), MaxToolTransientError),
        (ConcurrencyLimitExceeded(), MaxToolTransientError),
        (ClickHouseQueryTimeOut(), MaxToolRetryableError),
        (ValueError("nope"), MaxToolRetryableError),
    ],
)
def test_to_max_tool_error_classification(error, expected_cls):
    wrapped = to_max_tool_error(error, "boom")
    assert isinstance(wrapped, expected_cls)
    assert str(wrapped) == "boom"
