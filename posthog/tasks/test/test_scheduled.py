from typing import cast

from django.test import TestCase

from celery import Celery
from celery.canvas import Signature
from celery.schedules import crontab

from posthog.celery import app
from posthog.tasks.scheduled import setup_periodic_tasks


class RecordingCelery:
    def __init__(self) -> None:
        self.calls: list[tuple[object, Signature, dict[str, object]]] = []

    def add_periodic_task(self, schedule: object, task_signature: Signature, **kwargs: object) -> None:
        self.calls.append((schedule, task_signature, kwargs))


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

        setup_periodic_tasks(cast(Celery, sender))

        schedule, task_signature, kwargs = next(
            call for call in sender.calls if call[2]["name"] == "reconcile proactive artifact adoptions"
        )
        assert isinstance(schedule, crontab)
        assert schedule.minute == {0, 10, 20, 30, 40, 50}
        assert task_signature.task == "products.subscriptions.backend.tasks.reconcile_proactive_artifact_adoptions"
        assert kwargs["expires"] == 9 * 60
        assert any("args" in call_kwargs for _schedule, _signature, call_kwargs in sender.calls)
