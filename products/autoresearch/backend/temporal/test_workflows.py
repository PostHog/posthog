from datetime import UTC, datetime
from typing import Any, Optional

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import User

from products.autoresearch.backend.models import AutoresearchPipeline, AutoresearchTrainingRun
from products.autoresearch.backend.temporal.workflows import (
    InferenceWorkflowResult,
    KickoffTrainingInput,
    KickoffTrainingResult,
    LoadActivePipelinesInput,
    RunInferenceInput,
    RunInferenceResult,
    RunValidationInput,
    RunValidationResult,
    ValidationWorkflowResult,
    activity_kickoff_training,
    activity_load_active_pipelines,
    activity_run_inference,
    activity_run_validation,
    evaluate_pipeline_outcome,
)
from products.autoresearch.backend.testing import TeamScopedTestMixin


def _inference(status: str = "completed", error: Optional[str] = None) -> InferenceWorkflowResult:
    return InferenceWorkflowResult(run_id="run-1", rows_scored=10, status=status, error=error)


def _validation(status: str = "completed", error: Optional[str] = None) -> ValidationWorkflowResult:
    return ValidationWorkflowResult(dates_validated=1, total_rows=10, status=status, error=error)


def _kickoff(reason: str = "started", error: Optional[str] = None) -> KickoffTrainingResult:
    return KickoffTrainingResult(kicked_off=reason == "started", reason=reason, error=error)


class TestEvaluatePipelineOutcome(SimpleTestCase):
    @parameterized.expand(
        [
            ("all_steps_succeed", _inference(), _validation(), _kickoff(), True, 0),
            ("inference_raises", RuntimeError("boom"), _validation(), _kickoff(), False, 1),
            ("inference_soft_fails", _inference(status="failed", error="oom"), _validation(), _kickoff(), False, 1),
            ("validation_raises", _inference(), RuntimeError("boom"), _kickoff(), False, 1),
            ("validation_soft_fails", _inference(), _validation(status="failed", error="boom"), _kickoff(), False, 1),
            ("kickoff_raises", _inference(), _validation(), RuntimeError("boom"), False, 1),
            ("kickoff_errors", _inference(), _validation(), _kickoff(reason="error", error="boom"), False, 1),
            ("kickoff_no_creator", _inference(), _validation(), _kickoff(reason="no_creator", error="boom"), False, 1),
            ("kickoff_skip_is_not_failure", _inference(), _validation(), _kickoff(reason="budget_exhausted"), True, 0),
            ("not_due_runs_validation_only", None, _validation(), None, True, 0),
            (
                "multiple_failures_all_counted",
                RuntimeError("boom"),
                _validation(status="failed", error="boom"),
                _kickoff(),
                False,
                2,
            ),
        ]
    )
    def test_outcome_classification(
        self,
        _name: str,
        inference: Any,
        validation: Any,
        kickoff: Any,
        expected_succeeded: bool,
        expected_error_count: int,
    ) -> None:
        outcome = evaluate_pipeline_outcome(
            pipeline_id="pipeline-1", inference=inference, validation=validation, kickoff=kickoff
        )
        assert outcome.succeeded == expected_succeeded
        assert len(outcome.errors) == expected_error_count


@time_machine.travel("2026-09-11T12:00:00Z", tick=False)
class TestCoordinatorActivities(TeamScopedTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        access = patch("products.autoresearch.backend.temporal.workflows.has_autoresearch_access", return_value=True)
        self.mock_access = access.start()
        self.addCleanup(access.stop)

    def _create_pipeline(self, **overrides: Any) -> AutoresearchPipeline:
        params: dict[str, Any] = {
            "team": self.team,
            "created_by": self.user,
            "name": "test pipeline",
            "target_event": "$pageview",
            "status": AutoresearchPipeline.Status.RUNNING,
            "iteration_budget_remaining": 20,
            **overrides,
        }
        return AutoresearchPipeline.objects.create(**params)

    @parameterized.expand(
        [
            ("never_scored_is_due", AutoresearchPipeline.Status.RUNNING, 1, None, True),
            ("overdue_is_due", AutoresearchPipeline.Status.RUNNING, 1, datetime(2026, 9, 9, 3), True),
            (
                "scored_yesterday_after_the_tick_is_due",
                AutoresearchPipeline.Status.RUNNING,
                1,
                datetime(2026, 9, 10, 23),
                True,
            ),
            ("scored_today_validates_only", AutoresearchPipeline.Status.RUNNING, 1, datetime(2026, 9, 11, 11), False),
            (
                "within_cadence_window_validates_only",
                AutoresearchPipeline.Status.RUNNING,
                7,
                datetime(2026, 9, 8, 3),
                False,
            ),
            ("past_cadence_window_is_due", AutoresearchPipeline.Status.RUNNING, 7, datetime(2026, 9, 4, 3), True),
            ("converged_overdue_is_due", AutoresearchPipeline.Status.CONVERGED, 1, datetime(2026, 9, 9, 3), True),
            ("paused_is_excluded", AutoresearchPipeline.Status.PAUSED, 1, None, None),
        ]
    )
    def test_load_active_pipelines_honors_cadence(
        self,
        _name: str,
        status: str,
        cadence_days: int,
        scored_at: Optional[datetime],
        expected_score_due: Optional[bool],
    ) -> None:
        pipeline = self._create_pipeline(
            status=status,
            cadence_days=cadence_days,
            last_scored_at=scored_at.replace(tzinfo=UTC) if scored_at else None,
        )
        result = activity_load_active_pipelines(LoadActivePipelinesInput())
        score_due = {p.pipeline_id: p.score_due for p in result.pipelines}.get(str(pipeline.id))
        assert score_due == expected_score_due

    @parameterized.expand([("creator_lost_access", True), ("outside_the_rollout", False)])
    def test_load_active_pipelines_excludes_pipelines_it_cannot_run(
        self, _name: str, creator_lost_access: bool
    ) -> None:
        if creator_lost_access:
            pipeline = self._create_pipeline(created_by=User.objects.create(email="left@example.com"))
        else:
            self.mock_access.return_value = False
            pipeline = self._create_pipeline()

        result = activity_load_active_pipelines(LoadActivePipelinesInput())

        assert str(pipeline.id) not in [p.pipeline_id for p in result.pipelines]
        pipeline.refresh_from_db()
        expected = AutoresearchPipeline.Status.PAUSED if creator_lost_access else AutoresearchPipeline.Status.RUNNING
        assert pipeline.status == expected

    @parameterized.expand([("inference",), ("validation",)])
    @patch("products.autoresearch.backend.temporal.workflows.run_online_validation_for_pipeline")
    @patch("products.autoresearch.backend.temporal.workflows.run_inference_for_pipeline")
    def test_activities_skip_a_pipeline_paused_after_discovery(
        self, step: str, mock_inference: MagicMock, mock_validation: MagicMock
    ) -> None:
        pipeline = self._create_pipeline(status=AutoresearchPipeline.Status.PAUSED)

        result: RunInferenceResult | RunValidationResult
        if step == "inference":
            result = activity_run_inference(
                RunInferenceInput(
                    pipeline_id=str(pipeline.id), team_id=self.team.id, model_id="unused", prediction_date="2026-09-11"
                )
            )
        else:
            result = activity_run_validation(RunValidationInput(pipeline_id=str(pipeline.id), team_id=self.team.id))

        assert result.status == "skipped"
        mock_inference.assert_not_called()
        mock_validation.assert_not_called()

    @patch("products.autoresearch.backend.temporal.workflows.run_training")
    def test_kickoff_passes_pipeline_creator_to_training(self, mock_run_training: MagicMock) -> None:
        pipeline = self._create_pipeline()

        result = activity_kickoff_training(KickoffTrainingInput(pipeline_id=str(pipeline.id), team_id=self.team.id))

        assert result.kicked_off
        assert result.reason == "started"
        mock_run_training.assert_called_once()
        assert mock_run_training.call_args.kwargs["user_id"] == self.user.id
        pipeline.refresh_from_db()
        assert pipeline.iteration_budget_remaining == 10

    @patch("products.autoresearch.backend.temporal.workflows.run_training")
    def test_kickoff_without_creator_fails_loudly_and_spends_no_budget(self, mock_run_training: MagicMock) -> None:
        pipeline = self._create_pipeline(created_by=None)

        result = activity_kickoff_training(KickoffTrainingInput(pipeline_id=str(pipeline.id), team_id=self.team.id))

        assert not result.kicked_off
        assert result.reason == "no_creator"
        assert result.error
        mock_run_training.assert_not_called()
        pipeline.refresh_from_db()
        assert pipeline.iteration_budget_remaining == 20

    @patch("products.autoresearch.backend.temporal.workflows.run_training")
    def test_kickoff_waits_for_a_pending_run(self, mock_run_training: MagicMock) -> None:
        pipeline = self._create_pipeline()
        AutoresearchTrainingRun.objects.create(
            pipeline=pipeline, status=AutoresearchTrainingRun.Status.PENDING, iteration_budget=10
        )

        result = activity_kickoff_training(KickoffTrainingInput(pipeline_id=str(pipeline.id), team_id=self.team.id))

        assert result.reason == "already_running"
        mock_run_training.assert_not_called()

    @parameterized.expand([("transient_failure_raises", RuntimeError("boom")), ("refused_launch", ValueError("left"))])
    @patch("products.autoresearch.backend.temporal.workflows.run_training")
    def test_failed_launch_spends_no_budget(self, _name: str, error: Exception, mock_run_training: MagicMock) -> None:
        pipeline = self._create_pipeline()
        mock_run_training.side_effect = error

        if isinstance(error, RuntimeError):
            with self.assertRaises(RuntimeError):
                activity_kickoff_training(KickoffTrainingInput(pipeline_id=str(pipeline.id), team_id=self.team.id))
        else:
            result = activity_kickoff_training(KickoffTrainingInput(pipeline_id=str(pipeline.id), team_id=self.team.id))
            assert result.reason == "not_launchable"

        pipeline.refresh_from_db()
        assert pipeline.iteration_budget_remaining == 20
