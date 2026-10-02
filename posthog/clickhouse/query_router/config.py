import time
from collections.abc import Mapping
from enum import IntEnum, StrEnum
from functools import lru_cache
from typing import Any

import structlog

from posthog.dataclasses import frozen
from posthog.settings import CONSTANCE_CONFIG, TEST

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


# Every class may start a query while the pool is under its limit; the class decides only the order of the
# queue. The wait is the same for every class, so a class never joins the queue where a more important one
# would be refused. A waiting query holds a web thread or a worker slot, so the wait is short and a query
# joins the queue only when it is likely to start within it.
MAX_WAIT_SECONDS = 5.0


@frozen
class PoolBounds:
    floor: int
    ceiling: int

    def __post_init__(self) -> None:
        # With a ceiling of 0 no class may start a query, so every enforced query would wait and drop.
        if not 0 < self.floor <= self.ceiling:
            raise ValueError(f"need 0 < floor <= ceiling, got floor={self.floor} and ceiling={self.ceiling}")


# The rank of a waiter is query_class * RANK_CLASS_MULTIPLIER + first-seen epoch milliseconds, so a
# higher class always sorts first and equal classes sort by arrival. The multiplier must stay above
# any epoch-millisecond value and the sum below 2^53, the largest integer a Redis score keeps exact.
RANK_CLASS_MULTIPLIER = 10**13

# A waiter that has not polled for this long is treated as gone and stops blocking the waiters behind it.
STALE_WAITER_MS = 3_000

# Admission estimates how fast a pool frees slots from the releases and arrivals of this window. A short
# window makes the estimate follow a pool that stops draining within seconds.
DRAIN_WINDOW_MS = 5_000

# A query joins the queue only when its estimated wait is at most this fraction of MAX_WAIT_SECONDS. The
# estimate is rough, and a query that waits its full time and is dropped holds a worker for nothing, so the
# router refuses a doubtful query on arrival instead.
QUEUE_WAIT_MARGIN = 0.5

# The controller rewrites the limit every second. The expiry makes admission fall back to the pool
# ceiling when the controller stops.
LIMIT_TTL_SECONDS = 15

CONTROLLER_LEADER_KEY = "query_router:controller:leader"

# Epoch seconds of the last load read that reached every node of the cluster, or of the first partial
# read when no read has reached every node.
CONTROLLER_LAST_COMPLETE_SAMPLE_KEY = "query_router:controller:last_complete_sample"


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


def released_key(pool: Pool) -> str:
    return _key(pool, "released")


def arrivals_key(pool: Pool) -> str:
    return _key(pool, "arrivals")


def limit_key(pool: Pool) -> str:
    return _key(pool, "limit")


def load_key(pool: Pool) -> str:
    return _key(pool, "load")


def limit_updated_key(pool: Pool) -> str:
    return _key(pool, "limit_updated")


@frozen
class _RouterSettings:
    mode: RouterMode
    enforced: frozenset[tuple[Pool, QueryClass]]
    bounds: Mapping[Pool, PoolBounds]


def _enforced_pairs(raw: str) -> frozenset[tuple[Pool, QueryClass]]:
    pairs: set[tuple[Pool, QueryClass]] = set()
    for item in raw.split(","):
        pool_name, _, class_value = item.strip().partition(":")
        if not pool_name:
            continue
        pairs.add((Pool(pool_name), QueryClass(int(class_value))))
    return frozenset(pairs)


def _bounds_from(values: Mapping[str, Any]) -> dict[Pool, PoolBounds]:
    return {
        pool: PoolBounds(
            floor=int(values[f"QUERY_ROUTER_{pool.name}_FLOOR"]),
            ceiling=int(values[f"QUERY_ROUTER_{pool.name}_CEILING"]),
        )
        for pool in Pool
    }


_SETTING_KEYS = [
    "QUERY_ROUTER_MODE",
    "QUERY_ROUTER_ENFORCE",
    *(f"QUERY_ROUTER_{pool.name}_{bound}" for pool in Pool for bound in ("FLOOR", "CEILING")),
]


# Every ClickHouse query asks for the mode, so the settings are read from Postgres at most once a
# minute per process. A failed read is cached for the same minute, which keeps a Postgres outage
# from adding a failed Postgres call to every ClickHouse query.
@lru_cache(maxsize=1)
def _load_settings(_minute: int) -> _RouterSettings:
    # posthog.models imports the ClickHouse client, and the client imports this package, so a
    # module-level import here is circular.
    from posthog.models.instance_setting import get_instance_settings  # noqa: PLC0415

    try:
        values = get_instance_settings(_SETTING_KEYS)
        mode = RouterMode(values["QUERY_ROUTER_MODE"])
        bounds = _bounds_from(values)
        try:
            enforced = _enforced_pairs(values["QUERY_ROUTER_ENFORCE"])
        except ValueError:
            # A mistyped enforce list stops enforcement but keeps the router counting.
            logger.warning("query_router_enforce_setting_invalid", value=values["QUERY_ROUTER_ENFORCE"])
            enforced = frozenset()
        return _RouterSettings(mode=mode, enforced=enforced, bounds=bounds)
    except Exception:
        # The settings table does not exist during the first Postgres migrations, and a mistyped
        # value must not take queries down. Both cases turn the router off.
        logger.warning("query_router_settings_unreadable", exc_info=True)
        defaults = {key: CONSTANCE_CONFIG[key][0] for key in _SETTING_KEYS}
        return _RouterSettings(mode=RouterMode.OFF, enforced=frozenset(), bounds=_bounds_from(defaults))


def _settings() -> _RouterSettings:
    return _load_settings(int(time.time() // 60))


def get_pool_bounds(pool: Pool) -> PoolBounds:
    return _settings().bounds[pool]


def get_global_mode() -> RouterMode:
    if TEST:
        return RouterMode.OFF
    return _settings().mode


def get_mode(pool: Pool, query_class: QueryClass) -> RouterMode:
    mode = get_global_mode()
    if mode != RouterMode.ENFORCE:
        return mode
    return RouterMode.ENFORCE if (pool, query_class) in _settings().enforced else RouterMode.OBSERVE
