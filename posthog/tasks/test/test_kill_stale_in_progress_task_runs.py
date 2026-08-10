import datetime
from typing import TYPE_CHECKING, Any, ClassVar

from unittest.mock import patch

from django.apps import apps
from django.test import TestCase, override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.tasks.tasks import kill_stale_in_progress_task_runs

if TYPE_CHECKING:
    from products.tasks.backend.models import Task, TaskRun

CAP_SECONDS = 3 * 60 * 60
# The sweep window is the cap plus a one-hour grace, so 4h is the boundary.
STALE = datetime.timedelta(hours=4, minutes=1)
FRESH = datetime.timedelta(hours=3, minutes=59)
# Uncapped (interactive) runs are swept on the Temporal execution timeout plus the same grace, so
# with the cap well under the 12h floor the boundary is 13h.
UNCAPPED_STALE = datetime.timedelta(hours=13, minutes=1)
UNCAPPED_FRESH = datetime.timedelta(hours=12, minutes=59)


@override_settings(TASKS_MAX_RUN_DURATION_SECONDS=CAP_SECONDS)
class TestKillStaleInProgressTaskRuns(TestCase):
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
        updated_age: datetime.timedelta,
        *,
        environment: str | None = None,
        state: dict | None = None,
    ) -> "TaskRun":
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=status,
            **({"environment": environment} if environment else {}),
            **({"state": state} if state is not None else {}),
        )
        TaskRun.objects.filter(pk=run.pk).update(updated_at=timezone.now() - updated_age)
        run.refresh_from_db()
        return run

    def test_marks_stale_in_progress_cloud_run_as_failed(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = self._make_run(TaskRun.Status.IN_PROGRESS, STALE)

        with patch("products.tasks.backend.models.posthoganalytics.capture") as mock_capture:
            kill_stale_in_progress_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.FAILED)
        self.assertIn("stuck in IN_PROGRESS", run.error_message or "")
        self.assertIsNotNone(run.completed_at)
        captured = [c for c in mock_capture.call_args_list if c.kwargs.get("event") == "task_run_failed"]
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].kwargs["properties"]["error_type"], "stale_in_progress_cleanup")

    def test_leaves_run_inside_the_window_alone(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = self._make_run(TaskRun.Status.IN_PROGRESS, FRESH)

        kill_stale_in_progress_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.IN_PROGRESS)

    @override_settings(TASKS_MAX_RUN_DURATION_SECONDS=12 * 60 * 60)
    def test_window_tracks_the_configured_run_duration_cap(self) -> None:
        # The sweep must not reap runs the workflow is still legitimately allowed to run.
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = self._make_run(TaskRun.Status.IN_PROGRESS, STALE)

        kill_stale_in_progress_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.IN_PROGRESS)

    def test_leaves_local_runs_alone(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = self._make_run(TaskRun.Status.IN_PROGRESS, STALE, environment=TaskRun.Environment.LOCAL)

        kill_stale_in_progress_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.IN_PROGRESS)

    def test_leaves_interactive_runs_inside_the_execution_timeout_alone(self) -> None:
        # Interactive sessions are exempt from the workflow's wall-clock cap, and nothing on the
        # live path writes the run row, so a quiet updated_at is not evidence of a dead workflow
        # anywhere inside the Temporal execution timeout.
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = self._make_run(TaskRun.Status.IN_PROGRESS, STALE, state={"mode": "interactive"})
        near_ceiling = self._make_run(TaskRun.Status.IN_PROGRESS, UNCAPPED_FRESH, state={"mode": "interactive"})

        kill_stale_in_progress_task_runs()

        run.refresh_from_db()
        near_ceiling.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.IN_PROGRESS)
        self.assertEqual(near_ceiling.status, TaskRun.Status.IN_PROGRESS)

    def test_sweeps_interactive_runs_past_the_execution_timeout(self) -> None:
        # The execution timeout is the only bound an interactive session has, and Temporal enforces
        # it server-side without the workflow getting to write its terminal status. Past that
        # ceiling the row has no writer left, so excluding interactive runs outright would strand
        # them IN_PROGRESS forever.
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = self._make_run(TaskRun.Status.IN_PROGRESS, UNCAPPED_STALE, state={"mode": "interactive"})

        kill_stale_in_progress_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.FAILED)

    def test_leaves_local_interactive_runs_alone_at_any_age(self) -> None:
        # A local session has no Temporal execution behind it at all, so the ceiling proves nothing.
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = self._make_run(
            TaskRun.Status.IN_PROGRESS,
            UNCAPPED_STALE,
            environment=TaskRun.Environment.LOCAL,
            state={"mode": "interactive"},
        )

        kill_stale_in_progress_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.IN_PROGRESS)

    @parameterized.expand([({},), ({"mode": "background"},), ({"prewarmed": True},)])
    def test_sweeps_runs_without_an_interactive_mode(self, state: dict) -> None:
        # An absent `mode` key means background. Excluding on a JSON key naively would compare
        # against NULL and skip every one of these rows, silently disabling the sweep.
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = self._make_run(TaskRun.Status.IN_PROGRESS, STALE, state=state)

        kill_stale_in_progress_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.FAILED)

    @override_settings(TASKS_MAX_RUN_DURATION_SECONDS=20 * 60 * 60)
    def test_uncapped_window_tracks_a_cap_raised_past_the_execution_timeout_floor(self) -> None:
        # The execution timeout is derived from the cap, so a cap above the floor pushes both the
        # ceiling and this window out with it rather than letting the ceiling preempt the cap.
        TaskRun = apps.get_model("tasks", "TaskRun")
        inside = self._make_run(TaskRun.Status.IN_PROGRESS, UNCAPPED_STALE, state={"mode": "interactive"})
        outside = self._make_run(
            TaskRun.Status.IN_PROGRESS, datetime.timedelta(hours=22, minutes=1), state={"mode": "interactive"}
        )

        kill_stale_in_progress_task_runs()

        inside.refresh_from_db()
        outside.refresh_from_db()
        self.assertEqual(inside.status, TaskRun.Status.IN_PROGRESS)
        self.assertEqual(outside.status, TaskRun.Status.FAILED)

    @override_settings(TASKS_MAX_RUN_DURATION_SECONDS=0)
    def test_disabled_cap_falls_back_to_the_execution_timeout_window(self) -> None:
        # 0 disables the in-workflow cap, so the only remaining bound is the 12h Temporal execution
        # timeout. Treating the disabled cap as a zero-second window would reap every run older
        # than the grace hour.
        TaskRun = apps.get_model("tasks", "TaskRun")
        inside = self._make_run(TaskRun.Status.IN_PROGRESS, datetime.timedelta(hours=12, minutes=30))
        outside = self._make_run(TaskRun.Status.IN_PROGRESS, datetime.timedelta(hours=13, minutes=30))

        kill_stale_in_progress_task_runs()

        inside.refresh_from_db()
        outside.refresh_from_db()
        self.assertEqual(inside.status, TaskRun.Status.IN_PROGRESS)
        self.assertEqual(outside.status, TaskRun.Status.FAILED)

    @parameterized.expand(
        [
            (apps.get_model("tasks", "TaskRun").Status.NOT_STARTED,),
            (apps.get_model("tasks", "TaskRun").Status.QUEUED,),
            (apps.get_model("tasks", "TaskRun").Status.COMPLETED,),
            (apps.get_model("tasks", "TaskRun").Status.FAILED,),
            (apps.get_model("tasks", "TaskRun").Status.CANCELLED,),
        ]
    )
    def test_leaves_non_in_progress_runs_alone(self, status: str) -> None:
        run = self._make_run(status, STALE)

        kill_stale_in_progress_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, status)

    def test_caps_work_at_batch_size(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        for _ in range(550):
            self._make_run(TaskRun.Status.IN_PROGRESS, STALE)

        kill_stale_in_progress_task_runs()

        self.assertEqual(TaskRun.objects.filter(status=TaskRun.Status.FAILED).count(), 500)
        self.assertEqual(TaskRun.objects.filter(status=TaskRun.Status.IN_PROGRESS).count(), 50)

    def test_one_failure_does_not_block_the_sweep(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        run_a = self._make_run(TaskRun.Status.IN_PROGRESS, STALE)
        run_b = self._make_run(TaskRun.Status.IN_PROGRESS, STALE + datetime.timedelta(hours=1))
        call_count = {"n": 0}

        def flaky_mark_failed(self: Any, error: str, error_type: str | None = None) -> None:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("synthetic failure")

        with (
            patch.object(TaskRun, "mark_failed", flaky_mark_failed),
            patch("posthog.tasks.tasks.capture_exception") as mock_capture,
        ):
            kill_stale_in_progress_task_runs()

        mock_capture.assert_called_once()
        run_a.refresh_from_db()
        run_b.refresh_from_db()
        # claim_and_fail_stale_run flips the status before finalizing, so both rows leave
        # IN_PROGRESS; only the sweep counters distinguish the finalizer that raised.
        self.assertEqual([run_a.status, run_b.status], [TaskRun.Status.FAILED, TaskRun.Status.FAILED])

    def test_skips_run_a_workflow_terminalized_between_select_and_claim(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = self._make_run(TaskRun.Status.IN_PROGRESS, STALE)
        TaskRun.objects.filter(pk=run.pk).update(status=TaskRun.Status.COMPLETED)

        with patch(
            "products.tasks.backend.facade.api.get_stale_in_progress_cloud_task_run_ids",
            return_value=[run.pk],
        ):
            kill_stale_in_progress_task_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.COMPLETED)
        self.assertIsNone(run.error_message)
