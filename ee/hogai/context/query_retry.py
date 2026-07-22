import random
import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import structlog

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryMemoryLimitExceeded

from ee.hogai.tool_errors import MaxToolError, MaxToolRetryableError, MaxToolTransientError

logger = structlog.get_logger(__name__)

T = TypeVar("T")

# ClickHouse errors that self-heal once load subsides. Max AI queries run through a dedicated
# `max_ai` ClickHouse user with a small org-wide concurrency cap, so a fan-out of queries routinely
# trips TOO_MANY_SIMULTANEOUS_QUERIES (surfaced as ClickHouseAtCapacity) or a transient memory-limit
# error. These are worth retrying as-is rather than dead-ending the user or asking them to adjust inputs.
TRANSIENT_QUERY_ERRORS: tuple[type[Exception], ...] = (
    ClickHouseAtCapacity,
    ClickHouseQueryMemoryLimitExceeded,
    ConcurrencyLimitExceeded,
)


def is_transient_query_error(err: BaseException) -> bool:
    return isinstance(err, TRANSIENT_QUERY_ERRORS)


def to_max_tool_error(err: Exception, message: str) -> MaxToolError:
    """Wrap a query-execution error into the right MaxToolError so the agent handles it well.

    Transient capacity errors become a MaxToolTransientError (retry once, unchanged); everything
    else stays a MaxToolRetryableError (the agent may retry with adjusted inputs).
    """
    if is_transient_query_error(err):
        return MaxToolTransientError(message)
    return MaxToolRetryableError(message)


async def aretry_transient_query(
    thunk: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 4,
    base_delay_s: float = 0.5,
    max_delay_s: float = 5.0,
) -> T:
    """Run `thunk`, retrying on transient ClickHouse capacity errors with jittered exponential backoff.

    Non-transient errors propagate immediately. Used by the Max AI query paths so a transient
    capacity spike self-heals instead of surfacing to the user as a failed query.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return await thunk()
        except Exception as err:
            # Non-transient errors, and the final attempt, propagate to the caller unchanged.
            if not is_transient_query_error(err) or attempt >= max_attempts:
                raise
            delay = min(base_delay_s * (2 ** (attempt - 1)), max_delay_s)
            delay += random.uniform(0, delay / 2)  # jitter so fanned-out queries don't retry in lockstep
            logger.warning(
                "max_ai_query_capacity_retry",
                attempt=attempt,
                max_attempts=max_attempts,
                delay_s=round(delay, 2),
                error=str(err),
            )
            await asyncio.sleep(delay)
    raise RuntimeError("aretry_transient_query exhausted its loop without returning or raising")
