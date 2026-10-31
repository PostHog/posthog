from datetime import timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from django.utils import timezone as django_timezone

from posthog.test.base import BaseTest

from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchPipeline,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.testing import TeamScopedTestMixin
from products.autoresearch.backend.training.stale import (
    AUTORESEARCH_STALE_TRAINING_RUNS_REAPED,
    fail_stale_training_runs,
)
from products.tasks.backend.facade.contracts import TaskRunDTO


class TestStaleTrainingRuns(TeamScopedTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.pipeline = AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="Stale Test Pipeline",
            target_event="$pageview",
            horizon_days=7,
            iteration_budget=10,
            status=AutoresearchPipeline.Status.RUNNING,
        )

    def _make_training_run(self, **kwargs) -> AutoresearchTrainingRun:
        defaults = {
            "pipeline": self.pipeline,
            "status": AutoresearchTrainingRun.Status.RUNNING,
            "iteration_budget": 10,
            "agent_runtime_adapter": "anthropic",
            "agent_model": "claude-opus-5-5",
            "task_id": uuid4(),
            "task_run_id": uuid4(),
            "started_at": django_timezone.now(),
        }
        defaults.update(kwargs)
        return AutoresearchTrainingRun.objects.create(**defaults)

    def _make_task_run_dto(self, run: AutoresearchTrainingRun, status: str, is_terminal: bool) -> TaskRunDTO:
        return TaskRunDTO(
            id=run.task_run_id,
            task_id=run.task_id,
            team_id=self.team.id,
            status=status,
            environment="sandbox",
            stage=None,
            branch=None,
            error_message=None,
            output=None,
            state={"autoresearch_training_run_id": str(run.id)},
            is_terminal=is_terminal,
        )

    @patch("products.autoresearch.backend.training.stale.tasks_cancellation.cancel_task_run")
    @patch("products.autoresearch.backend.training.stale.tasks_facade.get_task_run")
    def test_lost_driver_past_cutoff_is_failed_and_task_cancelled(
        self, mock_get_task_run: MagicMock, mock_cancel_task_run: MagicMock
    ):
        past_time = django_timezone.now() - timedelta(hours=3)
        run = self._make_training_run()
        AutoresearchTrainingRun.objects.filter(pk=run.pk).update(created_at=past_time)

        # TaskRun is still live (in_progress, not terminal)
        task_run_dto = self._make_task_run_dto(run, status="in_progress", is_terminal=False)
        mock_get_task_run.return_value = task_run_dto

        reaped = fail_stale_training_runs(team_id=self.team.id, cutoff_delta=timedelta(hours=1))

        assert reaped == 1
        run.refresh_from_db()
        assert run.status == AutoresearchTrainingRun.Status.FAILED
        assert "Training sandbox stopped without a result" in run.error
        assert run.completed_at is not None
        mock_cancel_task_run.assert_called_once_with(
            run.task_run_id,
            run.task_id,
            self.team.id,
            reason="Autoresearch training run timed out past the sandbox TTL ceiling",
            source="autoresearch",
        )

    @patch("products.autoresearch.backend.training.stale.handle_task_run_completed")
    @patch("products.autoresearch.backend.training.stale.tasks_facade.get_task_run")
    def test_missed_handoff_past_cutoff_is_finalized(
        self, mock_get_task_run: MagicMock, mock_handle_completed: MagicMock
    ):
        past_time = django_timezone.now() - timedelta(hours=3)
        run = self._make_training_run()
        AutoresearchTrainingRun.objects.filter(pk=run.pk).update(created_at=past_time)

        # TaskRun reached terminal status (completed)
        task_run_dto = self._make_task_run_dto(run, status="completed", is_terminal=True)
        mock_get_task_run.return_value = task_run_dto

        reaped = fail_stale_training_runs(team_id=self.team.id, cutoff_delta=timedelta(hours=1))

        assert reaped == 1
        mock_handle_completed.assert_called_once()
        passed_arg = mock_handle_completed.call_args[0][0]
        assert passed_arg.id == run.task_run_id
        assert passed_arg.status == "completed"

    @patch("products.autoresearch.backend.training.stale.tasks_facade.get_task_run")
    def test_run_inside_cutoff_is_untouched(self, mock_get_task_run: MagicMock):
        # Run created just now (well inside cutoff)
        run = self._make_training_run()

        reaped = fail_stale_training_runs(team_id=self.team.id, cutoff_delta=timedelta(hours=1))

        assert reaped == 0
        run.refresh_from_db()
        assert run.status == AutoresearchTrainingRun.Status.RUNNING
        mock_get_task_run.assert_not_called()

    @patch("products.autoresearch.backend.training.stale.tasks_facade.get_task_run")
    def test_external_run_opened_with_open_training_run_is_untouched(self, mock_get_task_run: MagicMock):
        past_time = django_timezone.now() - timedelta(hours=3)
        # External run has no task_id, no task_run_id, no agent_runtime_adapter
        run = self._make_training_run(
            task_id=None,
            task_run_id=None,
            agent_runtime_adapter=None,
            agent_model=None,
            kickoff_reason=AutoresearchTrainingRun.KickoffReason.MANUAL,
        )
        AutoresearchTrainingRun.objects.filter(pk=run.pk).update(created_at=past_time)

        reaped = fail_stale_training_runs(team_id=self.team.id, cutoff_delta=timedelta(hours=1))

        assert reaped == 0
        run.refresh_from_db()
        assert run.status == AutoresearchTrainingRun.Status.RUNNING
        mock_get_task_run.assert_not_called()

    @patch("products.autoresearch.backend.training.stale.tasks_facade.get_task_run")
    def test_lost_before_task_dispatch_is_failed(self, mock_get_task_run: MagicMock):
        past_time = django_timezone.now() - timedelta(hours=3)
        # Sandbox run that crashed before task dispatch: agent_runtime_adapter set, but task_run_id is None
        run = self._make_training_run(
            task_id=None,
            task_run_id=None,
            agent_runtime_adapter="anthropic",
        )
        AutoresearchTrainingRun.objects.filter(pk=run.pk).update(created_at=past_time)

        reaped = fail_stale_training_runs(team_id=self.team.id, cutoff_delta=timedelta(hours=1))

        assert reaped == 1
        run.refresh_from_db()
        assert run.status == AutoresearchTrainingRun.Status.FAILED
        assert "stopped before task dispatch completed" in run.error

    @patch("products.autoresearch.backend.training.stale.tasks_facade.get_task_run")
    def test_bootstrapping_pipeline_reverts_to_draft_on_failure(self, mock_get_task_run: MagicMock):
        self.pipeline.status = AutoresearchPipeline.Status.BOOTSTRAPPING
        self.pipeline.save(update_fields=["status"])

        past_time = django_timezone.now() - timedelta(hours=3)
        run = self._make_training_run(task_id=None, task_run_id=None, agent_runtime_adapter="anthropic")
        AutoresearchTrainingRun.objects.filter(pk=run.pk).update(created_at=past_time)

        reaped = fail_stale_training_runs(team_id=self.team.id, cutoff_delta=timedelta(hours=1))

        assert reaped == 1
        self.pipeline.refresh_from_db()
        assert self.pipeline.status == AutoresearchPipeline.Status.DRAFT
