"""
Celery tasks for agentic_tests.

`run_due_agentic_tests` is the periodic beat: every minute it claims any active
AgenticTest whose `next_run_at` has elapsed (FOR UPDATE SKIP LOCKED so multiple
workers don't double-fire), enqueues a per-run task for each, and advances
`next_run_at` to the next cron occurrence.

`run_agentic_test_run` does the actual execution against a single AgenticTestRun
row (created in RUNNING by the API or the beat). The HTTP "Run now" path creates
the row synchronously and dispatches this task so the request returns immediately.
"""

from django.db import transaction
from django.utils import timezone

import structlog
from celery import shared_task

from products.agentic_tests.backend.logic.execution import execute_agentic_test_run, queue_agentic_test_run
from products.agentic_tests.backend.logic.scheduling import compute_next_run_at
from products.agentic_tests.backend.models import AgenticTest

logger = structlog.get_logger(__name__)

MAX_BATCH = 50


@shared_task(ignore_result=True, queue="default")
def run_due_agentic_tests() -> None:
    """Pick up any active agentic tests whose next_run_at has elapsed and queue a run for each."""
    now = timezone.now()
    with transaction.atomic():
        due_tests = list(
            AgenticTest.objects.select_for_update(skip_locked=True)
            .filter(status=AgenticTest.Status.ACTIVE)
            .exclude(schedule_cron="")
            .filter(next_run_at__lte=now)
            .order_by("next_run_at")[:MAX_BATCH]
        )

        # Bump next_run_at first so subsequent ticks don't re-claim while we dispatch below.
        for test in due_tests:
            test.next_run_at = compute_next_run_at(test, base=now)
            test.save(update_fields=["next_run_at", "updated_at"])

    for test in due_tests:
        try:
            queue_agentic_test_run(test)
        except Exception as exc:  # noqa: BLE001
            logger.exception("agentic_test_enqueue_failed", test_id=str(test.id), error=str(exc))


@shared_task(ignore_result=True, queue="default")
def run_agentic_test_run(run_id: str) -> None:
    """Execute a single pending AgenticTestRun to completion."""
    try:
        execute_agentic_test_run(run_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("agentic_test_execution_failed", run_id=run_id, error=str(exc))
