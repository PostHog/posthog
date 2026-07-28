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

# A kind names a failure class that repeats on retry; transient conditions must never get one.
FailureKind = Literal["memory_limit", "timeout", "too_slow", "query_size"]

Budget = Literal["interactive", "extended"]
BUDGET_INTERACTIVE: Budget = "interactive"
BUDGET_EXTENDED: Budget = "extended"


@dataclass(frozen=True)
class KindPolicy:
    open_threshold: int
    max_backoff: timedelta
    timeout_independent: bool


KIND_POLICIES: dict[FailureKind, KindPolicy] = {
    # Peak memory varies run to run, so a query sitting near the ceiling can exceed it once and
    # then finish. One sample doesn't distinguish that from a query that can never fit.
    "memory_limit": KindPolicy(open_threshold=2, max_backoff=timedelta(minutes=30), timeout_independent=True),
    "timeout": KindPolicy(open_threshold=3, max_backoff=timedelta(minutes=30), timeout_independent=False),
    "too_slow": KindPolicy(open_threshold=3, max_backoff=timedelta(minutes=30), timeout_independent=False),
    # The query text is byte-identical for a given cache key, so its size cannot come in under the
    # limit on a retry. One failure is the whole story.
    "query_size": KindPolicy(open_threshold=1, max_backoff=timedelta(minutes=30), timeout_independent=True),
}

BASE_BACKOFF = timedelta(minutes=2)
RECORD_TTL = timedelta(hours=24)
# A breaker that only ratchets up counts failures hours apart as if they were consecutive, so a
# query attempted a handful of times over a working day ends up pinned at the ceiling. A failure
# older than this describes a different moment on the cluster, so the count starts over.
FAILURE_DECAY = timedelta(hours=1)


@dataclass(frozen=True)
class QueryFailureRecord:
    kind: FailureKind
    detail: str
    consecutive_failures: int
    last_failed_at: datetime
    open_until: Optional[datetime]
    budget: Budget = BUDGET_INTERACTIVE

    @property
    def is_open(self) -> bool:
        return self.open_until is not None and datetime.now(UTC) < self.open_until

    def forbids(self, budget: Budget) -> bool:
        """A failure observed under the extended budget forbids every run, and timeout-independent
        kinds forbid regardless. A failure observed under the interactive budget does not forbid
        extended-budget runs, which get more execution time and may well succeed."""
        if KIND_POLICIES[self.kind].timeout_independent or self.budget == BUDGET_EXTENDED:
            return True
        return budget == BUDGET_INTERACTIVE


def _decayed(record: QueryFailureRecord) -> bool:
    return datetime.now(UTC) - record.last_failed_at >= FAILURE_DECAY


class QueryFailureCache:
    """Per-cache-key circuit breaker for deterministically failing queries.

    Failures are counted per query cache key; once the kind's open threshold is reached, the
    breaker opens and requests that would otherwise recalculate skip the query until an
    exponentially growing backoff elapses — serving the cached result if there is one, and the
    remembered failure only when there isn't. Any successful calculation closes the breaker, and
    the count decays so failures far apart don't compound. Storage errors fail open: a broken
    cache backend makes this feature a no-op, never a query failure.
    """

    def __init__(self, cache_key: str) -> None:
        self.key = f"query_failure:{cache_key}"

    def get_open(self) -> Optional[QueryFailureRecord]:
        record = self._load()
        return record if record is not None and record.is_open else None

    def record_failure(
        self, kind: FailureKind, detail: str, budget: Budget = BUDGET_INTERACTIVE
    ) -> Optional[QueryFailureRecord]:
        """Count a deterministic failure. The detail is shown to users verbatim when the
        remembered failure is served, so callers must only ever pass user-safe copy."""
        policy = KIND_POLICIES.get(kind)
        if policy is None:
            # A caller bug, not a storage condition: surface it instead of failing open.
            raise ValueError(f"Unknown failure kind: {kind}")
        try:
            previous = self._load()
            failures = 1
            record_budget = budget
            if previous is not None and previous.kind == kind and not _decayed(previous):
                failures = previous.consecutive_failures + 1
                if previous.budget == BUDGET_EXTENDED:
                    # Once the big-budget path has failed, a later small-budget failure must
                    # not narrow what the breaker forbids.
                    record_budget = BUDGET_EXTENDED
            open_until: Optional[datetime] = None
            if failures >= policy.open_threshold:
                max_doublings = (policy.max_backoff // BASE_BACKOFF).bit_length()
                doublings = min(failures - policy.open_threshold, max_doublings)
                open_until = datetime.now(UTC) + min(BASE_BACKOFF * 2**doublings, policy.max_backoff)
            record = QueryFailureRecord(
                kind=kind,
                # Capped so record size stays bounded no matter what copy a caller passes.
                detail=detail[:1000],
                consecutive_failures=failures,
                last_failed_at=datetime.now(UTC),
                open_until=open_until,
                budget=record_budget,
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
            if data.get("kind") not in KIND_POLICIES:
                # A record written by a different code version (rolling deploy, rollback) must
                # read as "no record", never as an error.
                return None
            return QueryFailureRecord(
                kind=cast(FailureKind, data["kind"]),
                detail=data["detail"],
                consecutive_failures=data["consecutive_failures"],
                last_failed_at=datetime.fromisoformat(data["last_failed_at"]),
                open_until=datetime.fromisoformat(data["open_until"]) if data["open_until"] else None,
                budget=data.get("budget", BUDGET_INTERACTIVE),
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
            "budget": record.budget,
        }
