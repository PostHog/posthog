import datetime
from typing import ClassVar

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.tasks.tasks import kill_stale_queued_task_runs

from products.tasks.backend.models import Task, TaskRun


class TestKillStaleQueuedTaskRuns(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    task: ClassVar[Task]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.task = Task.objects.create(
            team=cls.team,
            title="Test Task",
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

    def _make_run(self, status: str, age: datetime.timedelta) -> TaskRun:
        run = TaskRun.objects.create(task=self.task, team=self.team, status=status)
        past = timezone.now() - age
        TaskRun.objects.filter(pk=run.pk).update(created_at=past, updated_at=past)
        run.refresh_from_db()
        return run

    def test_marks_stale_queued_run_as_failed(self):
        run = self._make_run(TaskRun.Status.QUEUED, datetime.timedelta(hours=25))

        kill_stale_queued_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.FAILED)
        self.assertIn("stuck in QUEUED", run.error_message or "")
        self.assertIsNotNone(run.completed_at)

    def test_leaves_recently_queued_run_alone(self):
        run = self._make_run(TaskRun.Status.QUEUED, datetime.timedelta(hours=23, minutes=59))

        kill_stale_queued_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.QUEUED)
        self.assertIsNone(run.completed_at)
        self.assertIsNone(run.error_message)

    def test_leaves_re_queued_run_with_old_created_at_alone(self):
        # prepare_for_cloud_handoff re-queues an existing run without resetting
        # created_at. A staleness check keyed on created_at would mistakenly mark
        # the freshly re-queued run as FAILED; updated_at (auto_now) protects it.
        run = self._make_run(TaskRun.Status.COMPLETED, datetime.timedelta(hours=48))
        run.prepare_for_cloud_handoff()

        kill_stale_queued_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.QUEUED)
        self.assertIsNone(run.completed_at)
        self.assertIsNone(run.error_message)

    @parameterized.expand(
        [
            (TaskRun.Status.NOT_STARTED,),
            (TaskRun.Status.IN_PROGRESS,),
            (TaskRun.Status.COMPLETED,),
            (TaskRun.Status.FAILED,),
            (TaskRun.Status.CANCELLED,),
        ]
    )
    def test_leaves_non_queued_runs_alone(self, status):
        run = self._make_run(status, datetime.timedelta(hours=48))

        kill_stale_queued_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, status)

    def test_caps_work_at_batch_size(self):
        for _ in range(550):
            self._make_run(TaskRun.Status.QUEUED, datetime.timedelta(hours=25))

        kill_stale_queued_task_runs()

        failed_count = TaskRun.objects.filter(status=TaskRun.Status.FAILED).count()
        remaining_queued = TaskRun.objects.filter(status=TaskRun.Status.QUEUED).count()
        self.assertEqual(failed_count, 500)
        self.assertEqual(remaining_queued, 50)

    def test_one_failure_does_not_block_the_sweep(self):
        run_a = self._make_run(TaskRun.Status.QUEUED, datetime.timedelta(hours=25))
        run_b = self._make_run(TaskRun.Status.QUEUED, datetime.timedelta(hours=26))

        original_mark_failed = TaskRun.mark_failed
        call_count = {"n": 0}

        def flaky_mark_failed(self, error: str):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("synthetic failure")
            return original_mark_failed(self, error)

        with (
            patch.object(TaskRun, "mark_failed", flaky_mark_failed),
            patch("posthog.tasks.tasks.capture_exception") as mock_capture,
        ):
            kill_stale_queued_task_runs()

        mock_capture.assert_called_once()
        run_a.refresh_from_db()
        run_b.refresh_from_db()
        statuses = sorted([run_a.status, run_b.status])
        self.assertEqual(statuses, sorted([TaskRun.Status.QUEUED, TaskRun.Status.FAILED]))

    def test_skips_run_whose_status_changed_between_select_and_update(self):
        run = self._make_run(TaskRun.Status.QUEUED, datetime.timedelta(hours=25))

        original_filter = TaskRun.objects.filter

        def stealing_filter(*args, **kwargs):
            qs = original_filter(*args, **kwargs)
            if kwargs.get("status") == TaskRun.Status.QUEUED and "pk" in kwargs:
                TaskRun.objects.filter(pk=run.pk).update(status=TaskRun.Status.IN_PROGRESS)
            return qs

        with patch.object(TaskRun.objects, "filter", side_effect=stealing_filter):
            kill_stale_queued_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.IN_PROGRESS)
        self.assertIsNone(run.error_message)
