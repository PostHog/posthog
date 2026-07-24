import time
from dataclasses import dataclass
from typing import Any, Literal, Optional, Union

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
# Failures are only relevant to followers already waiting; they poll every FLIGHT_POLL_INTERVAL.
FLIGHT_FAILURE_TTL = 5


@dataclass(frozen=True)
class FlightFailure:
    """The externally observable identity of a leader's failure: everything a follower needs
    to render a byte-identical error response, and nothing else."""

    status_code: int
    code: str
    detail: str


class QuerySingleFlight:
    """Collapses concurrent blocking executions of the same cache key onto one leader.

    Followers wait for the leader and then serve the fresh cache entry (success) or replay the
    failure envelope. Success needs no envelope: the leader's cache write is the publication.
    Storage errors always fail open to independent execution, never to a query failure.
    """

    def __init__(self, cache_key: str) -> None:
        self.lock_key = f"query_flight:{cache_key}"
        self.failure_key = f"query_flight_failure:{cache_key}"

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

    def record_failure(self, failure: FlightFailure) -> None:
        try:
            data: dict[str, Any] = {
                "status_code": failure.status_code,
                "code": failure.code,
                "detail": failure.detail,
            }
            caches[QUERY_CACHE_ALIAS].set(self.failure_key, data, FLIGHT_FAILURE_TTL)
        except Exception:
            logger.exception("query_single_flight_record_failed", key=self.failure_key)

    def get_failure(self) -> Optional[FlightFailure]:
        try:
            data = caches[QUERY_CACHE_ALIAS].get(self.failure_key)
            if not isinstance(data, dict):
                return None
            return FlightFailure(status_code=data["status_code"], code=data["code"], detail=data["detail"])
        except Exception:
            logger.exception("query_single_flight_read_failed", key=self.failure_key)
            return None

    def wait(self, timeout_seconds: float) -> Union[FlightFailure, Literal["released", "timeout"]]:
        """Poll until the leader shares a failure, releases the lock, or the timeout elapses.
        The failure check comes first each round: the leader writes the envelope before releasing."""
        deadline = time.monotonic() + timeout_seconds
        while True:
            failure = self.get_failure()
            if failure is not None:
                return failure
            if not self.in_flight():
                return "released"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "timeout"
            time.sleep(min(FLIGHT_POLL_INTERVAL, remaining))
