"""Async retry path for deleting Temporal schedules orphaned by a DB-side revert.

When `delete_saved_query_schedule` runs after a saved-query revert and the Temporal client
hits a transient transport failure (DNS lookup, UNAVAILABLE, etc.), the DB revert has already
committed. We can't reliably block the user's request waiting for Temporal to come back, so
the synchronous call hands off to this task to converge eventually instead of leaving the
schedule firing indefinitely.
"""

import structlog
import temporalio
from celery import Task, shared_task
from temporalio.service import RPCStatusCode

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import delete_schedule

logger = structlog.get_logger(__name__)


@shared_task(bind=True, max_retries=5, default_retry_delay=60, ignore_result=True)
def cleanup_orphaned_saved_query_schedule(self: Task, saved_query_id: str) -> None:
    """Best-effort deletion of a Temporal schedule that outlived a saved-query revert.

    Retries with exponential backoff. Treats NOT_FOUND as success (the schedule is already gone,
    either from a successful prior attempt or because it was never created).
    """
    try:
        temporal = sync_connect()
        delete_schedule(temporal, schedule_id=saved_query_id)
        logger.info(
            "cleanup_orphaned_saved_query_schedule_succeeded",
            saved_query_id=saved_query_id,
            retries=self.request.retries,
        )
    except temporalio.service.RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return
        _retry_or_give_up(self, e, saved_query_id)
    except RuntimeError as e:
        _retry_or_give_up(self, e, saved_query_id)


def _retry_or_give_up(task: Task, exc: BaseException, saved_query_id: str) -> None:
    countdown = min(60 * (2**task.request.retries), 600)
    try:
        raise task.retry(exc=exc, countdown=countdown)
    except task.MaxRetriesExceededError:
        capture_exception(exc, {"saved_query_id": saved_query_id})
        logger.exception(
            "cleanup_orphaned_saved_query_schedule_exhausted_retries",
            saved_query_id=saved_query_id,
            max_retries=task.max_retries,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        raise
