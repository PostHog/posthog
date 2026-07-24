from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Optional, cast

from django.core.cache import caches

import structlog
from prometheus_client import Counter

from posthog.caching.redis_cluster_connection_factory import QUERY_CACHE_ALIAS

logger = structlog.get_logger(__name__)

QUERY_FAILURE_CACHING_FLAG = "query-failure-caching"

QUERY_FAILURE_CACHE_COUNTER = Counter(
    "posthog_query_failure_cache_total",
    "Circuit-breaker activity for queries that keep failing deterministically",
    labelnames=["action", "kind"],
)

# Failure kinds are the breaker's contract with its callers: a kind names a class of failure
# that repeats on retry. Callers own the mapping between their exceptions and kinds; transient
# conditions (capacity, network, cancellations, cluster memory pressure) must never get a kind.
FailureKind = Literal["memory_limit", "timeout", "too_slow", "query_size"]

# These kinds fail the same way regardless of how much execution time the run was allowed.
BUDGET_INDEPENDENT_KINDS: frozenset[FailureKind] = frozenset({"memory_limit", "query_size"})

SCOPE_SYNC = "sync"
SCOPE_ASYNC = "async"

# Consecutive failures before the breaker opens, per kind. Query-size and per-query memory
# failures are properties of the query and its data, so a retry cannot succeed and the very
# first failure opens the breaker. Timeouts and too-slow estimates depend partly on cluster
# load, so they get three attempts.
OPEN_THRESHOLD: dict[FailureKind, int] = {
    "memory_limit": 1,
    "timeout": 3,
    "too_slow": 3,
    "query_size": 1,
}

BASE_BACKOFF = timedelta(minutes=2)
# Timeouts and too-slow estimates depend partly on cluster load (a quieter cluster can save a
# borderline query), so they get a much shorter maximum suppression window.
MAX_BACKOFF: dict[FailureKind, timedelta] = {
    "memory_limit": timedelta(hours=4),
    "timeout": timedelta(minutes=30),
    "too_slow": timedelta(minutes=30),
    "query_size": timedelta(hours=4),
}
RECORD_TTL = timedelta(hours=24)  # failure counts reset after a day without failures


@dataclass(frozen=True)
class QueryFailureRecord:
    kind: FailureKind
    detail: str
    consecutive_failures: int
    last_failed_at: datetime
    open_until: Optional[datetime]
    scope: str = SCOPE_SYNC

    @property
    def is_open(self) -> bool:
        return self.open_until is not None and datetime.now(UTC) < self.open_until

    @property
    def suppresses_async_dispatch(self) -> bool:
        """A timeout under the small interactive budget must not suppress the async path, which
        gets 10x the execution time and may well succeed."""
        return self.kind in BUDGET_INDEPENDENT_KINDS or self.scope == SCOPE_ASYNC


class QueryFailureCache:
    """Per-cache-key circuit breaker for deterministically failing queries.

    Failures are counted per query cache key; once the kind's open threshold is reached, the
    breaker opens and requests that would otherwise recalculate are served the remembered
    failure until an exponentially growing backoff elapses. Any successful calculation closes
    the breaker. Storage errors fail open: a broken cache backend makes this feature a no-op,
    never a query failure.
    """

    def __init__(self, cache_key: str) -> None:
        self.key = f"query_failure:{cache_key}"

    def get_open(self) -> Optional[QueryFailureRecord]:
        record = self._load()
        return record if record is not None and record.is_open else None

    def record_failure(self, kind: FailureKind, detail: str, scope: str = SCOPE_SYNC) -> Optional[QueryFailureRecord]:
        """Count a deterministic failure. The detail is shown to users verbatim when the
        remembered failure is served, so callers must only ever pass user-safe copy."""
        if kind not in OPEN_THRESHOLD:
            # A caller bug, not a storage condition: surface it instead of failing open.
            raise ValueError(f"Unknown failure kind: {kind}")
        try:
            previous = self._load()
            failures = 1
            record_scope = scope
            if previous is not None and previous.kind == kind:
                failures = previous.consecutive_failures + 1
                if previous.scope == SCOPE_ASYNC:
                    # Once the big-budget path has failed, a later small-budget failure must
                    # not narrow what the breaker suppresses.
                    record_scope = SCOPE_ASYNC
            open_until: Optional[datetime] = None
            if failures >= OPEN_THRESHOLD[kind]:
                # The exponent must be clamped before multiplying: timedelta arithmetic
                # overflows around 2**40, and 2**10 already exceeds every MAX_BACKOFF cap.
                backoff = BASE_BACKOFF * 2 ** min(failures - OPEN_THRESHOLD[kind], 10)
                open_until = datetime.now(UTC) + min(backoff, MAX_BACKOFF[kind])
            record = QueryFailureRecord(
                kind=kind,
                # Capped so record size stays bounded no matter what copy a caller passes.
                detail=detail[:1000],
                consecutive_failures=failures,
                last_failed_at=datetime.now(UTC),
                open_until=open_until,
                scope=record_scope,
            )
            caches[QUERY_CACHE_ALIAS].set(self.key, self._serialize(record), RECORD_TTL.total_seconds())
            QUERY_FAILURE_CACHE_COUNTER.labels(action="opened" if open_until else "recorded", kind=kind).inc()
            return record
        except Exception:
            logger.exception("query_failure_cache_write_failed", key=self.key)
            return None

    def clear(self) -> None:
        try:
            if caches[QUERY_CACHE_ALIAS].delete(self.key):
                QUERY_FAILURE_CACHE_COUNTER.labels(action="cleared", kind="any").inc()
        except Exception:
            logger.exception("query_failure_cache_clear_failed", key=self.key)

    def _load(self) -> Optional[QueryFailureRecord]:
        try:
            data = caches[QUERY_CACHE_ALIAS].get(self.key)
            if not isinstance(data, dict):
                return None
            if data.get("kind") not in OPEN_THRESHOLD:
                # A record written by a different code version (rolling deploy, rollback) must
                # read as "no record", never as an error.
                return None
            return QueryFailureRecord(
                kind=cast(FailureKind, data["kind"]),
                detail=data["detail"],
                consecutive_failures=data["consecutive_failures"],
                last_failed_at=datetime.fromisoformat(data["last_failed_at"]),
                open_until=datetime.fromisoformat(data["open_until"]) if data["open_until"] else None,
                scope=data.get("scope", SCOPE_SYNC),
            )
        except Exception:
            logger.exception("query_failure_cache_read_failed", key=self.key)
            return None

    @staticmethod
    def _serialize(record: QueryFailureRecord) -> dict[str, Any]:
        return {
            "kind": record.kind,
            "detail": record.detail,
            "consecutive_failures": record.consecutive_failures,
            "last_failed_at": record.last_failed_at.isoformat(),
            "open_until": record.open_until.isoformat() if record.open_until else None,
            "scope": record.scope,
        }
