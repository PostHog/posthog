import datetime
from typing import TYPE_CHECKING, ClassVar

from unittest.mock import patch

from django.apps import apps
from django.test import TestCase
from django.utils import timezone

from posthog.models import Organization, Team
from posthog.tasks.tasks import redispatch_orphaned_queued_task_runs

if TYPE_CHECKING:
    from products.tasks.backend.models import Task, TaskRun


class TestRedispatchOrphanedQueuedTaskRuns(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    task: ClassVar["Task"]

    @classmethod
    def setUpTestData(cls) -> None:
        Task = apps.get_model("tasks", "Task")
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.task = Task.objects.create(
            team=cls.team,
            title="Test Task",
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

    def _queued_run(self, updated_age: datetime.timedelta) -> "TaskRun":
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = TaskRun.objects.create(task=self.task, team=self.team, status=TaskRun.Status.QUEUED)
        now = timezone.now()
        TaskRun.objects.filter(pk=run.pk).update(created_at=now - updated_age, updated_at=now - updated_age)
        return run

    def test_redispatches_run_queued_past_grace_window(self) -> None:
        run = self._queued_run(datetime.timedelta(minutes=10))

        with patch(
            "products.tasks.backend.facade.api.redispatch_task_run", return_value="recovered"
        ) as mock_redispatch:
            redispatch_orphaned_queued_task_runs()

        mock_redispatch.assert_called_once_with(run.id)

    def test_leaves_run_within_grace_window_for_normal_dispatch(self) -> None:
        # Normal dispatch flips QUEUED->IN_PROGRESS in under a second; the reconciler must not
        # race it. A regression widening the grace to the killer's 24h would make this useless.
        self._queued_run(datetime.timedelta(minutes=1))

        with patch(
            "products.tasks.backend.facade.api.redispatch_task_run", return_value="recovered"
        ) as mock_redispatch:
            redispatch_orphaned_queued_task_runs()

        mock_redispatch.assert_not_called()

    def test_one_failure_does_not_block_the_sweep(self) -> None:
        self._queued_run(datetime.timedelta(minutes=10))
        self._queued_run(datetime.timedelta(minutes=11))

        call_count = {"n": 0}

        def flaky_redispatch(run_id: object) -> str:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("synthetic failure")
            return "recovered"

        with (
            patch("products.tasks.backend.facade.api.redispatch_task_run", side_effect=flaky_redispatch),
            patch("posthog.tasks.tasks.capture_exception") as mock_capture,
        ):
            redispatch_orphaned_queued_task_runs()

        mock_capture.assert_called_once()
        self.assertEqual(call_count["n"], 2)
