from django.test import TestCase

from celery.schedules import crontab

from posthog.celery import app
from posthog.tasks.scheduled import setup_periodic_tasks


class RecordingCelery:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object, str | None, float | None]] = []

    def add_periodic_task(
        self, schedule: object, task_signature: object, name: str | None = None, expires: float | None = None
    ) -> None:
        self.calls.append((schedule, task_signature, name, expires))


class TestScheduledTasks(TestCase):
    def test_scheduled_tasks(self) -> None:
        """
        `setup_periodic_tasks` may fail silently. This test ensures that it doesn't.
        """
        try:
            setup_periodic_tasks(app)
        except Exception as exc:
            assert exc is None, exc

    def test_registers_proactive_artifact_reconciliation_every_ten_minutes(self) -> None:
        sender = RecordingCelery()

        setup_periodic_tasks(sender)  # type: ignore[arg-type]

        schedule, task_signature, name, expires = next(
            call for call in sender.calls if call[2] == "reconcile proactive artifact adoptions"
        )
        assert isinstance(schedule, crontab)
        assert schedule.minute == {0, 10, 20, 30, 40, 50}
        assert task_signature.task == "products.subscriptions.backend.tasks.reconcile_proactive_artifact_adoptions"
        assert expires == 9 * 60
