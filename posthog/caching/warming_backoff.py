from datetime import UTC, datetime, timedelta
from typing import Optional

from django.core.cache import caches

import structlog

from posthog.caching.redis_cluster_connection_factory import QUERY_CACHE_ALIAS

logger = structlog.get_logger(__name__)

FAILURES_BEFORE_BACKOFF = 2
BASE_BACKOFF = timedelta(hours=2)
MAX_BACKOFF = timedelta(hours=8)
RECORD_TTL = timedelta(hours=24)


class WarmingBackoff:
    """Consecutive failed warms of one insight on one dashboard, and the wait they impose.

    The query failure breaker in posthog/query_cache/failures.py only remembers failures that
    repeat for every run of a query, because it replays them to people. Warming can afford to
    wait after any failure, including the capacity errors the breaker must never remember.
    Storage errors fail open: a broken cache backend means no backoff, never a failed warm.
    """

    def __init__(self, *, team_id: int, insight_id: int, dashboard_id: Optional[int]) -> None:
        self._key = f"warming_backoff:{team_id}:{insight_id}:{dashboard_id or ''}"
        self._failures, self._retry_at = self._load()

    @property
    def is_waiting(self) -> bool:
        return self._retry_at is not None and datetime.now(UTC) < self._retry_at

    def record_failure(self) -> None:
        failures = self._failures + 1
        retry_at = None
        if failures >= FAILURES_BEFORE_BACKOFF:
            doublings = min(failures - FAILURES_BEFORE_BACKOFF, MAX_BACKOFF // BASE_BACKOFF)
            retry_at = datetime.now(UTC) + min(BASE_BACKOFF * 2**doublings, MAX_BACKOFF)
        try:
            caches[QUERY_CACHE_ALIAS].set(
                self._key,
                {"failures": failures, "retry_at": retry_at.isoformat() if retry_at else None},
                RECORD_TTL.total_seconds(),
            )
        except Exception:
            logger.exception("warming_backoff_write_failed", key=self._key)

    def clear(self) -> None:
        if not self._failures:
            return
        self._failures, self._retry_at = 0, None
        try:
            caches[QUERY_CACHE_ALIAS].delete(self._key)
        except Exception:
            logger.exception("warming_backoff_clear_failed", key=self._key)

    def _load(self) -> tuple[int, Optional[datetime]]:
        try:
            data = caches[QUERY_CACHE_ALIAS].get(self._key)
            if not isinstance(data, dict):
                return 0, None
            retry_at = data.get("retry_at")
            return int(data["failures"]), datetime.fromisoformat(retry_at) if retry_at else None
        except Exception:
            logger.exception("warming_backoff_read_failed", key=self._key)
            return 0, None
