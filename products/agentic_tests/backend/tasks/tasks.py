"""
Celery tasks for agentic_tests.

`run_due_agentic_tests` is the heartbeat: every minute beat fires it, it claims any
active AgenticTest whose `next_run_at` has elapsed (FOR UPDATE SKIP LOCKED so multiple
workers don't double-fire), runs it, and advances `next_run_at` from the cron schedule.
"""

from django.db import transaction
from django.utils import timezone

import structlog
from celery import shared_task

from products.agentic_tests.backend.logic.execution import execute_agentic_test
from products.agentic_tests.backend.logic.scheduling import compute_next_run_at
from products.agentic_tests.backend.models import AgenticTest

logger = structlog.get_logger(__name__)

MAX_BATCH = 50


@shared_task(ignore_result=True, queue="default")
def run_due_agentic_tests() -> None:
    """Pick up any active agentic tests whose next_run_at has elapsed and execute them."""
    now = timezone.now()
    with transaction.atomic():
        due_tests = list(
            AgenticTest.objects.select_for_update(skip_locked=True)
            .filter(status=AgenticTest.Status.ACTIVE)
            .exclude(schedule_cron="")
            .filter(next_run_at__lte=now)
            .order_by("next_run_at")[:MAX_BATCH]
        )

        # Bump next_run_at first so subsequent ticks don't re-claim while we execute below.
        for test in due_tests:
            test.next_run_at = compute_next_run_at(test, base=now)
            test.save(update_fields=["next_run_at", "updated_at"])

    for test in due_tests:
        try:
            execute_agentic_test(test)
        except Exception as exc:  # noqa: BLE001
            logger.exception("agentic_test_execution_failed", test_id=str(test.id), error=str(exc))
