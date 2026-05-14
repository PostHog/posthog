"""Helpers for scheduled agentic test runs."""

from datetime import datetime

from django.utils import timezone

from croniter import croniter

from products.agentic_tests.backend.models import AgenticTest


def compute_next_run_at(test: AgenticTest, base: datetime | None = None) -> datetime | None:
    """
    Return the next time this test should fire, or None if it shouldn't.

    A test is scheduled iff it has a non-empty `schedule_cron` and is `active`.
    Paused / proposed / rejected tests always return None.
    """
    if test.status != AgenticTest.Status.ACTIVE:
        return None
    if not test.schedule_cron:
        return None
    try:
        itr = croniter(test.schedule_cron, base or timezone.now())
        return itr.get_next(datetime)
    except (ValueError, KeyError):
        return None


def refresh_next_run_at(test: AgenticTest) -> None:
    """Recompute and persist `next_run_at` based on the test's current schedule + status."""
    test.next_run_at = compute_next_run_at(test)
    test.save(update_fields=["next_run_at", "updated_at"])
