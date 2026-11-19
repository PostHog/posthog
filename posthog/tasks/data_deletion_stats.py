import uuid
from datetime import datetime

from django.core.cache import caches
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.models.data_deletion_request import DataDeletionRequest, refresh_deletion_stats
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

# The stats run two ClickHouse queries of up to 300 seconds each, so the hard limit is past both.
REFRESH_SOFT_TIME_LIMIT_SECONDS = 660
REFRESH_TIME_LIMIT_SECONDS = 720
# A task that waited longer than this in the queue is dropped, so the lease never outlives a queued task.
QUEUE_WAIT_SECONDS = 15 * 60
FAILURE_TTL_SECONDS = 60 * 60
CACHE_ALIAS = "data_deletion_stats"


class DeletionStatsRefresh:
    """Counts a deletion request's matching events in the background, and keeps its state for the console.

    One fetch at a time holds a lease with its own token. The task renews the lease when a worker picks it up
    and releases it only while it still owns it, so a slow or expired task never frees a newer fetch's lease.
    """

    def __init__(self, request_id: object) -> None:
        self.request_id = str(request_id)
        self._running_key = f"data_deletion_stats_refresh:{self.request_id}:running"
        self._failure_key = f"data_deletion_stats_refresh:{self.request_id}:failure"

    def _lease(self) -> dict | None:
        return caches[CACHE_ALIAS].get(self._running_key)

    def _owns_lease(self, token: str) -> bool:
        lease = self._lease()
        return lease is not None and lease["token"] == token

    def running_since(self) -> datetime | None:
        lease = self._lease()
        return datetime.fromisoformat(lease["since"]) if lease is not None else None

    def last_failure(self) -> str | None:
        return caches[CACHE_ALIAS].get(self._failure_key)

    def start(self, user_id: int | None) -> bool:
        """Queue the refresh. Returns False when one is already running for this request."""
        token = uuid.uuid4().hex
        lease = {"since": timezone.now().isoformat(), "token": token}
        if not caches[CACHE_ALIAS].add(
            self._running_key, lease, timeout=QUEUE_WAIT_SECONDS + REFRESH_TIME_LIMIT_SECONDS
        ):
            return False
        caches[CACHE_ALIAS].delete(self._failure_key)
        try:
            refresh_deletion_stats_task.apply_async(args=(self.request_id, user_id, token), expires=QUEUE_WAIT_SECONDS)
        except Exception:
            caches[CACHE_ALIAS].delete(self._running_key)
            raise
        return True

    def run(self, user_id: int | None, token: str) -> None:
        lease = self._lease()
        if lease is None or lease["token"] != token:
            logger.info("data_deletion_stats_refresh_superseded", request_id=self.request_id)
            return
        caches[CACHE_ALIAS].set(self._running_key, lease, timeout=REFRESH_TIME_LIMIT_SECONDS)
        try:
            request = DataDeletionRequest.objects.get(pk=self.request_id)
            refresh_deletion_stats(request, user_id=user_id)
        except Exception as error:
            caches[CACHE_ALIAS].set(self._failure_key, str(error), timeout=FAILURE_TTL_SECONDS)
            logger.exception("data_deletion_stats_refresh_failed", request_id=self.request_id)
        finally:
            if self._owns_lease(token):
                caches[CACHE_ALIAS].delete(self._running_key)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    soft_time_limit=REFRESH_SOFT_TIME_LIMIT_SECONDS,
    time_limit=REFRESH_TIME_LIMIT_SECONDS,
)
@skip_team_scope_audit
def refresh_deletion_stats_task(request_id: str, user_id: int | None, token: str) -> None:
    DeletionStatsRefresh(request_id).run(user_id, token)
