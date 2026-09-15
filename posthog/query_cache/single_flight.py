import time
import uuid
from datetime import datetime
from typing import Literal, Optional

import structlog
from prometheus_client import Counter, Histogram

from posthog.dataclasses import frozen
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
# Followers poll every FLIGHT_POLL_INTERVAL, so the published result only has to outlive a few polls.
FLIGHT_RESULT_TTL = 5

# Both scripts act only while this leader still owns the lock, so a leader that outlived
# FLIGHT_LOCK_TTL cannot touch the lock of the leader that replaced it.
_RELEASE_OWN_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""

_PUBLISH_RESULT_AND_RELEASE_OWN_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    redis.call("set", KEYS[2], ARGV[2], "EX", ARGV[3])
    return redis.call("del", KEYS[1])
end
return 0
"""

FlightOutcome = Literal["done", "released", "timeout"]


@frozen
class FlightWait:
    outcome: FlightOutcome
    # last_refresh of the entry the leader wrote, present only when the outcome is "done".
    last_refresh: Optional[datetime] = None


class QuerySingleFlight:
    """Collapses concurrent blocking executions of one cache key onto one leader.

    Followers wait for the leader, then serve the cache entry it published or run the query
    themselves. Failures are never transported: repeated failures are the circuit breaker's
    concern. Storage errors fail open to independent execution, never to a query failure.
    """

    def __init__(self, cache_key: str) -> None:
        # The hash tag keeps both keys in one Redis Cluster slot so the release script can touch both.
        self.lock_key = f"query_flight:{{{cache_key}}}"
        self.result_key = f"query_flight_result:{{{cache_key}}}"
        self._token = uuid.uuid4().hex

    def acquire(self) -> bool:
        try:
            client = storage.query_cache_raw_client()
            return bool(client.set(self.lock_key, self._token, nx=True, ex=FLIGHT_LOCK_TTL))
        except Exception:
            logger.exception("query_single_flight_acquire_failed", key=self.lock_key)
            return True

    def release(self, *, last_refresh: Optional[datetime] = None) -> None:
        """Release the lock, publishing which entry the leader wrote when it has one to publish."""
        try:
            client = storage.query_cache_raw_client()
            # redis-py's stubs omit register_script on RedisCluster; the runtime supports it.
            if last_refresh is None:
                client.register_script(_RELEASE_OWN_LOCK_SCRIPT)(keys=[self.lock_key], args=[self._token])  # type: ignore[union-attr]
            else:
                client.register_script(_PUBLISH_RESULT_AND_RELEASE_OWN_LOCK_SCRIPT)(  # type: ignore[union-attr]
                    keys=[self.lock_key, self.result_key],
                    args=[self._token, last_refresh.isoformat(), FLIGHT_RESULT_TTL],
                )
        except Exception:
            logger.exception("query_single_flight_release_failed", key=self.lock_key)

    def wait(self, timeout_seconds: float) -> FlightWait:
        """Poll until the leader releases the lock or the timeout elapses."""
        start = time.monotonic()
        deadline = start + timeout_seconds
        result = FlightWait(outcome="timeout")
        while True:
            if not self._in_flight():
                result = self._published_result()
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(FLIGHT_POLL_INTERVAL, remaining))
        QUERY_SINGLE_FLIGHT_WAIT_SECONDS.observe(time.monotonic() - start)
        return result

    def _in_flight(self) -> bool:
        try:
            return bool(storage.query_cache_raw_client().exists(self.lock_key))
        except Exception:
            return False

    def _published_result(self) -> FlightWait:
        try:
            value = storage.query_cache_raw_client().get(self.result_key)
        except Exception:
            return FlightWait(outcome="released")
        if value is None:
            return FlightWait(outcome="released")
        raw = value.decode() if isinstance(value, bytes) else str(value)
        return FlightWait(outcome="done", last_refresh=datetime.fromisoformat(raw))
