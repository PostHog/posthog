import datetime
from typing import TYPE_CHECKING, Any, ClassVar

from unittest.mock import patch

from django.apps import apps
from django.test import TestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.tasks.tasks import kill_stale_queued_task_runs

if TYPE_CHECKING:
    from products.tasks.backend.models import Task, TaskRun


class TestKillStaleQueuedTaskRuns(TestCase):
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

    def _make_run(
        self,
        status: str,
        age: datetime.timedelta,
        updated_age: datetime.timedelta | None = None,
        *,
        prewarmed: bool = False,
        environment: str | None = None,
    ) -> "TaskRun":
        TaskRun = apps.get_model("tasks", "TaskRun")
        state = {"prewarmed": True, "await_user_message": True} if prewarmed else {}
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=status,
            state=state,
            **({"environment": environment} if environment else {}),
        )
        now = timezone.now()
        TaskRun.objects.filter(pk=run.pk).update(
            created_at=now - age, updated_at=now - (updated_age if updated_age is not None else age)
        )
        run.refresh_from_db()
        return run

    def test_marks_stale_queued_run_as_failed(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = self._make_run(TaskRun.Status.QUEUED, datetime.timedelta(hours=25))

        kill_stale_queued_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.FAILED)
        self.assertIn("stuck in QUEUED", run.error_message or "")
        self.assertIsNotNone(run.completed_at)

    def test_leaves_recently_queued_run_alone(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = self._make_run(TaskRun.Status.QUEUED, datetime.timedelta(hours=23, minutes=59))

        kill_stale_queued_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.QUEUED)
        self.assertIsNone(run.completed_at)
        self.assertIsNone(run.error_message)

    def test_completes_stale_local_run_quietly_instead_of_failing(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        stale_local = self._make_run(
            TaskRun.Status.QUEUED, datetime.timedelta(hours=25), environment=TaskRun.Environment.LOCAL
        )
        fresh_local = self._make_run(
            TaskRun.Status.QUEUED, datetime.timedelta(hours=23, minutes=59), environment=TaskRun.Environment.LOCAL
        )
        # A local run whose updated_at keeps advancing is a live desktop session (the desktop
        # PATCHes output/branch as it works) — the created_at hard cap must never reap it.
        live_local = self._make_run(
            TaskRun.Status.QUEUED,
            datetime.timedelta(hours=50),
            updated_age=datetime.timedelta(hours=2),
            environment=TaskRun.Environment.LOCAL,
        )

        with patch("products.tasks.backend.push_dispatcher.notify_task_run_completed") as mock_notify:
            kill_stale_queued_task_runs()

        stale_local.refresh_from_db()
        self.assertEqual(stale_local.status, TaskRun.Status.COMPLETED)
        self.assertIsNone(stale_local.error_message)
        self.assertIsNotNone(stale_local.completed_at)
        mock_notify.assert_not_called()

        fresh_local.refresh_from_db()
        live_local.refresh_from_db()
        self.assertEqual(fresh_local.status, TaskRun.Status.QUEUED)
        self.assertEqual(live_local.status, TaskRun.Status.QUEUED)

    def test_leaves_re_queued_run_with_old_created_at_alone(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
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

    def test_reaps_orphaned_prewarmed_run_well_before_24h(self) -> None:
        # A prewarmed run whose workflow never started has no in-workflow timer to finalize it,
        # so it must be reaped on the short prewarmed window rather than riding QUEUED to 24h.
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = self._make_run(TaskRun.Status.QUEUED, datetime.timedelta(minutes=31), prewarmed=True)

        kill_stale_queued_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.FAILED)
        self.assertIn("orphaned in QUEUED", run.error_message or "")
        self.assertIsNotNone(run.completed_at)

    def test_spares_prewarmed_run_still_inside_idle_window(self) -> None:
        # A live warm run idles in QUEUED awaiting its first message; it must not be killed before
        # the in-workflow WARM_IDLE_TIMEOUT (10m) has had a chance to finalize an abandoned one.
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = self._make_run(TaskRun.Status.QUEUED, datetime.timedelta(minutes=10), prewarmed=True)

        kill_stale_queued_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.QUEUED)
        self.assertIsNone(run.error_message)

    def test_hard_cap_reaps_ancient_run_with_bumped_updated_at(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = self._make_run(
            TaskRun.Status.QUEUED,
            datetime.timedelta(hours=50),
            updated_age=datetime.timedelta(hours=2),
        )

        kill_stale_queued_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.FAILED)
        self.assertIsNotNone(run.completed_at)

    def test_hard_cap_spares_ancient_run_touched_within_grace(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = self._make_run(
            TaskRun.Status.QUEUED,
            datetime.timedelta(hours=50),
            updated_age=datetime.timedelta(minutes=10),
        )

        kill_stale_queued_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.QUEUED)
        self.assertIsNone(run.error_message)

    @parameterized.expand(
        [
            (apps.get_model("tasks", "TaskRun").Status.NOT_STARTED,),
            (apps.get_model("tasks", "TaskRun").Status.IN_PROGRESS,),
            (apps.get_model("tasks", "TaskRun").Status.COMPLETED,),
            (apps.get_model("tasks", "TaskRun").Status.FAILED,),
            (apps.get_model("tasks", "TaskRun").Status.CANCELLED,),
        ]
    )
    def test_leaves_non_queued_runs_alone(self, status: str) -> None:
        run = self._make_run(status, datetime.timedelta(hours=48))

        kill_stale_queued_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, status)

    def test_caps_work_at_batch_size(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        for _ in range(550):
            self._make_run(TaskRun.Status.QUEUED, datetime.timedelta(hours=25))

        kill_stale_queued_task_runs()

        failed_count = TaskRun.objects.filter(status=TaskRun.Status.FAILED).count()
        remaining_queued = TaskRun.objects.filter(status=TaskRun.Status.QUEUED).count()
        self.assertEqual(failed_count, 500)
        self.assertEqual(remaining_queued, 50)

    def test_one_failure_does_not_block_the_sweep(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        run_a = self._make_run(TaskRun.Status.QUEUED, datetime.timedelta(hours=25))
        run_b = self._make_run(TaskRun.Status.QUEUED, datetime.timedelta(hours=26))

        original_mark_failed = TaskRun.mark_failed
        call_count = {"n": 0}

        def flaky_mark_failed(self: Any, error: str) -> None:
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

    def test_skips_run_whose_status_changed_between_select_and_update(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = self._make_run(TaskRun.Status.QUEUED, datetime.timedelta(hours=25))

        original_filter = TaskRun.objects.filter

        def stealing_filter(*args: object, **kwargs: object) -> object:
            qs = original_filter(*args, **kwargs)
            if kwargs.get("status") == TaskRun.Status.QUEUED and "pk" in kwargs:
                TaskRun.objects.filter(pk=run.pk).update(status=TaskRun.Status.IN_PROGRESS)
            return qs

        with patch.object(TaskRun.objects, "filter", side_effect=stealing_filter):
            kill_stale_queued_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.IN_PROGRESS)
        self.assertIsNone(run.error_message)
