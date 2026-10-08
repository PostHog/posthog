import time
from collections.abc import Mapping
from enum import IntEnum, StrEnum
from functools import lru_cache
from typing import Any

import structlog

from posthog.dataclasses import frozen
from posthog.settings import TEST

logger = structlog.get_logger(__name__)


class Pool(StrEnum):
    """A set of ClickHouse nodes that share one admission limit."""

    OFFLINE = "offline"
    ONLINE = "online"


class QueryClass(IntEnum):
    """Priority of a query. A lower value is admitted first and dropped last."""

    INTERACTIVE = 1
    API = 2
    ASYNC = 3
    BACKGROUND = 4


class RouterMode(StrEnum):
    OFF = "off"
    # Count every query but never make one wait.
    OBSERVE = "observe"
    ENFORCE = "enforce"
    ERROR = "error"


# Every class may start a query while the pool is under its limit; the class decides only the order of the
# queue. The wait is the same for every class, so a class never joins the queue where a more important one
# would be refused. A waiting query holds a web thread or a worker slot, so the wait is short and a query
# joins the queue only when it is likely to start within it.
MAX_WAIT_SECONDS = 5.0

# The rank of a waiter is query_class * RANK_CLASS_MULTIPLIER + first-seen epoch milliseconds, so a
# higher class always sorts first and equal classes sort by arrival. The multiplier must stay above
# any epoch-millisecond value and the sum below 2^53, the largest integer a Redis score keeps exact.
RANK_CLASS_MULTIPLIER = 10**13

# A waiter that has not polled for this long is treated as gone and stops blocking the waiters behind it.
STALE_WAITER_MS = 3_000

# Admission estimates the wait from the average duration of the last queries that finished in the pool:
# a full pool frees limit / average slots per second. The average follows a change in query duration
# within this many finishes.
DURATION_HISTORY = 100

# Queries of a higher class that arrive while a query waits take the freed slots before it. The rate of
# those arrivals is measured over this window.
ARRIVALS_WINDOW_MS = 5_000

# A query joins the queue only when its estimated wait is at most this fraction of MAX_WAIT_SECONDS. The
# estimate is rough, and a query that waits its full time and is dropped holds a worker for nothing, so the
# router refuses a doubtful query on arrival instead.
QUEUE_WAIT_MARGIN = 0.5


def _key(pool: Pool, suffix: str) -> str:
    # The braces make every key of a pool hash to one Redis Cluster slot, which a Lua script that
    # touches several keys requires.
    return f"{{query_router:{pool.value}}}:{suffix}"


def running_key(pool: Pool, query_class: QueryClass) -> str:
    return _key(pool, f"running:{query_class.value}")


def waiting_key(pool: Pool) -> str:
    return _key(pool, "waiting")


def waiting_seen_key(pool: Pool) -> str:
    return _key(pool, "waiting_seen")


def durations_key(pool: Pool) -> str:
    return _key(pool, "durations")


def arrivals_key(pool: Pool) -> str:
    return _key(pool, "arrivals")


@frozen
class RouterSettings:
    mode: RouterMode
    enforced: frozenset[tuple[Pool, QueryClass]]
    limits: Mapping[Pool, int]

    def mode_for(self, pool: Pool, query_class: QueryClass) -> RouterMode:
        if self.mode != RouterMode.ENFORCE:
            return self.mode
        return RouterMode.ENFORCE if (pool, query_class) in self.enforced else RouterMode.OBSERVE


_OFF = RouterSettings(mode=RouterMode.OFF, enforced=frozenset(), limits={})
_ERROR = RouterSettings(mode=RouterMode.ERROR, enforced=frozenset(), limits={})


def _enforced_pairs(raw: str) -> frozenset[tuple[Pool, QueryClass]]:
    pairs: set[tuple[Pool, QueryClass]] = set()
    for item in raw.split(","):
        pool_name, _, class_value = item.strip().partition(":")
        if not pool_name:
            continue
        pairs.add((Pool(pool_name), QueryClass(int(class_value))))
    return frozenset(pairs)


def _limits_from(values: Mapping[str, Any]) -> dict[Pool, int]:
    limits = {pool: int(values[f"QUERY_ROUTER_{pool.name}_LIMIT"]) for pool in Pool}
    for pool, limit in limits.items():
        # With a limit of 0 no query may start, so every enforced query would wait and drop.
        if limit <= 0:
            raise ValueError(f"QUERY_ROUTER_{pool.name}_LIMIT must be positive, got {limit}")
    return limits


_SETTING_KEYS = [
    "QUERY_ROUTER_MODE",
    "QUERY_ROUTER_ENFORCE",
    *(f"QUERY_ROUTER_{pool.name}_LIMIT" for pool in Pool),
]


# Every ClickHouse query asks for the settings, so they are read from Postgres at most once a
# minute per process. A failed read is cached for the same minute, which keeps a Postgres outage
# from adding a failed Postgres call to every ClickHouse query.
@lru_cache(maxsize=1)
def _load_settings(_minute: int) -> RouterSettings:
    # posthog.models imports the ClickHouse client, and the client imports this package, so a
    # module-level import here is circular.
    from posthog.models.instance_setting import get_instance_settings  # noqa: PLC0415

    try:
        values = get_instance_settings(_SETTING_KEYS)
        mode = RouterMode(values["QUERY_ROUTER_MODE"])
        if mode == RouterMode.OFF:
            return _OFF
        limits = _limits_from(values)
        enforced = _enforced_pairs(values["QUERY_ROUTER_ENFORCE"])
        return RouterSettings(mode=mode, enforced=enforced, limits=limits)
    except Exception:
        # The settings table does not exist during the first Postgres migrations, and a mistyped
        # value must not take queries down. Distinguish this from an intentional off switch so
        # queries that bypass admission still count toward the failed-open alert.
        logger.warning("query_router_settings_unreadable", exc_info=True)
        return _ERROR


def get_settings() -> RouterSettings:
    """The settings as of this minute. A query reads them once, so its mode and its limit agree."""
    if TEST:
        return _OFF
    return _load_settings(int(time.time() // 60))
