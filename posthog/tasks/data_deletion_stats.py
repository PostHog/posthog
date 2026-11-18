from datetime import datetime

from django.core.cache import cache
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.models.data_deletion_request import DataDeletionRequest, refresh_deletion_stats
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

# The stats run two ClickHouse queries of up to 300 seconds each. The hard limit is past both, and the
# running marker expires with it, so a killed worker cannot block the next fetch.
REFRESH_SOFT_TIME_LIMIT_SECONDS = 660
REFRESH_TIME_LIMIT_SECONDS = 720
FAILURE_TTL_SECONDS = 60 * 60


class DeletionStatsRefresh:
    """Counts a deletion request's matching events in the background, and keeps its state for the console."""

    def __init__(self, request_id: object) -> None:
        self.request_id = str(request_id)
        self._running_key = f"data_deletion_stats_refresh:{self.request_id}:running_since"
        self._failure_key = f"data_deletion_stats_refresh:{self.request_id}:failure"

    def running_since(self) -> datetime | None:
        return cache.get(self._running_key)

    def last_failure(self) -> str | None:
        return cache.get(self._failure_key)

    def start(self, user_id: int | None) -> bool:
        """Queue the refresh. Returns False when one is already running for this request."""
        if not cache.add(self._running_key, timezone.now(), timeout=REFRESH_TIME_LIMIT_SECONDS):
            return False
        cache.delete(self._failure_key)
        try:
            refresh_deletion_stats_task.delay(self.request_id, user_id)
        except Exception:
            cache.delete(self._running_key)
            raise
        return True

    def run(self, user_id: int | None) -> None:
        try:
            request = DataDeletionRequest.objects.get(pk=self.request_id)
            refresh_deletion_stats(request, user_id=user_id)
        except Exception as error:
            cache.set(self._failure_key, str(error), timeout=FAILURE_TTL_SECONDS)
            logger.exception("data_deletion_stats_refresh_failed", request_id=self.request_id)
        finally:
            cache.delete(self._running_key)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    soft_time_limit=REFRESH_SOFT_TIME_LIMIT_SECONDS,
    time_limit=REFRESH_TIME_LIMIT_SECONDS,
)
@skip_team_scope_audit
def refresh_deletion_stats_task(request_id: str, user_id: int | None) -> None:
    DeletionStatsRefresh(request_id).run(user_id)
