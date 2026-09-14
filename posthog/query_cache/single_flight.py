import time
import uuid
from typing import Literal

import structlog
from prometheus_client import Counter, Histogram

from posthog.query_cache import storage

logger = structlog.get_logger(__name__)

QUERY_SINGLE_FLIGHT_FLAG = "query-single-flight"

QUERY_SINGLE_FLIGHT_COUNTER = Counter(
    "posthog_query_single_flight_total",
    "Blocking query executions by their role in a single flight",
    labelnames=["action"],
)

QUERY_SINGLE_FLIGHT_WAIT_SECONDS = Histogram(
    "posthog_query_single_flight_wait_seconds",
    "Time a follower spent waiting for the leader of an identical blocking query",
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30, 60],
)

# Sized past the interactive ClickHouse budget so an interactive leader always finishes while it
# holds the lock. A leader under the extended budget can outlive it; it then loses leadership and
# a follower may repeat the work, which is the behavior without single flight.
FLIGHT_LOCK_TTL = 90
FLIGHT_WAIT_SECONDS = 65
FLIGHT_POLL_INTERVAL = 0.25

# Deletes the lock only while this leader still owns it, so a leader that outlived
# FLIGHT_LOCK_TTL cannot remove the lock of the leader that replaced it.
_RELEASE_OWN_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""

FlightWaitOutcome = Literal["released", "timeout"]


class QuerySingleFlight:
    """Collapses concurrent blocking executions of one cache key onto one leader.

    Followers wait for the leader, then either serve the fresh cache entry it wrote or run the
    query themselves. Failures are never transported: repeated failures are the circuit
    breaker's concern. Storage errors fail open to independent execution, never to a query
    failure.
    """

    def __init__(self, cache_key: str) -> None:
        self.lock_key = f"query_flight:{cache_key}"
        self._token = uuid.uuid4().hex

    def acquire(self) -> bool:
        try:
            client = storage.query_cache_raw_client()
            return bool(client.set(self.lock_key, self._token, nx=True, ex=FLIGHT_LOCK_TTL))
        except Exception:
            logger.exception("query_single_flight_acquire_failed", key=self.lock_key)
            return True

    def release(self) -> None:
        try:
            client = storage.query_cache_raw_client()
            # redis-py's stubs omit register_script on RedisCluster; the runtime supports it.
            client.register_script(_RELEASE_OWN_LOCK_SCRIPT)(keys=[self.lock_key], args=[self._token])  # type: ignore[union-attr]
        except Exception:
            logger.exception("query_single_flight_release_failed", key=self.lock_key)

    def in_flight(self) -> bool:
        try:
            return bool(storage.query_cache_raw_client().exists(self.lock_key))
        except Exception:
            return False

    def wait(self, timeout_seconds: float) -> FlightWaitOutcome:
        """Poll until the leader releases the lock or the timeout elapses."""
        start = time.monotonic()
        deadline = start + timeout_seconds
        outcome: FlightWaitOutcome = "released"
        while self.in_flight():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                outcome = "timeout"
                break
            time.sleep(min(FLIGHT_POLL_INTERVAL, remaining))
        QUERY_SINGLE_FLIGHT_WAIT_SECONDS.observe(time.monotonic() - start)
        return outcome
