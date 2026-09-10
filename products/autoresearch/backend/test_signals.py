from uuid import UUID

from django.test import SimpleTestCase

from parameterized import parameterized

from products.autoresearch.backend.signals import on_task_run_saved
from products.tasks.backend.facade.api import TaskRunStatus


class TestOnTaskRunSaved(SimpleTestCase):
    @parameterized.expand([(["autoresearch_training_run_id"],), ("running",), (7,)])
    def test_non_object_task_run_state_does_not_raise(self, state) -> None:
        # Raising here would roll back the caller's terminal-status transaction.
        class FakeTaskRun:
            id = UUID("00000000-0000-0000-0000-000000000001")
            team_id = 1
            status = TaskRunStatus.COMPLETED
            state: object = None
            error_message: str | None = None

        instance = FakeTaskRun()
        instance.state = state

        on_task_run_saved(sender=None, instance=instance, created=False)
