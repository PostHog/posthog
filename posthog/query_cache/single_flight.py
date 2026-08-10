import time
from typing import Literal

from django.core.cache import caches

import structlog
from prometheus_client import Counter

from posthog.caching.redis_cluster_connection_factory import QUERY_CACHE_ALIAS

logger = structlog.get_logger(__name__)

QUERY_SINGLE_FLIGHT_FLAG = "query-single-flight"

QUERY_SINGLE_FLIGHT_COUNTER = Counter(
    "posthog_query_single_flight_total",
    "Concurrent identical blocking queries collapsed onto one execution",
    labelnames=["action"],
)

# Long enough to cover the interactive ClickHouse budget (60s); a leader running past it
# (async worker) just loses leadership and a follower may duplicate the work, which is the
# status quo without single flight.
FLIGHT_LOCK_TTL = 90
FLIGHT_WAIT_SECONDS = 65
FLIGHT_POLL_INTERVAL = 0.25


class QuerySingleFlight:
    """Collapses concurrent blocking executions of the same cache key onto one leader.

    Followers wait for the leader, then either serve the fresh cache entry it wrote or run the
    query themselves. Failures are never transported: a leader's repeated failures are the
    circuit breaker's concern. Storage errors always fail open to independent execution,
    never to a query failure.
    """

    def __init__(self, cache_key: str) -> None:
        self.lock_key = f"query_flight:{cache_key}"

    def acquire(self) -> bool:
        try:
            return bool(caches[QUERY_CACHE_ALIAS].add(self.lock_key, "1", FLIGHT_LOCK_TTL))
        except Exception:
            logger.exception("query_single_flight_acquire_failed", key=self.lock_key)
            return True

    def release(self) -> None:
        try:
            caches[QUERY_CACHE_ALIAS].delete(self.lock_key)
        except Exception:
            logger.exception("query_single_flight_release_failed", key=self.lock_key)

    def in_flight(self) -> bool:
        try:
            return caches[QUERY_CACHE_ALIAS].get(self.lock_key) is not None
        except Exception:
            return False

    def wait(self, timeout_seconds: float) -> Literal["released", "timeout"]:
        """Poll until the leader releases the lock or the timeout elapses."""
        deadline = time.monotonic() + timeout_seconds
        while True:
            if not self.in_flight():
                return "released"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "timeout"
            time.sleep(min(FLIGHT_POLL_INTERVAL, remaining))
