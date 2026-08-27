from datetime import timedelta
from typing import Any, Optional

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from products.autoresearch.backend.models import AutoresearchPipeline
from products.autoresearch.backend.temporal.workflows import (
    InferenceWorkflowResult,
    KickoffTrainingInput,
    KickoffTrainingResult,
    LoadActivePipelinesInput,
    ValidationWorkflowResult,
    activity_kickoff_training,
    activity_load_active_pipelines,
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


class TestCoordinatorActivities(TeamScopedTestMixin, BaseTest):
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
            ("overdue_is_due", AutoresearchPipeline.Status.RUNNING, 1, timedelta(days=2), True),
            ("recently_scored_is_not_due", AutoresearchPipeline.Status.RUNNING, 1, timedelta(hours=1), False),
            ("within_cadence_window_is_not_due", AutoresearchPipeline.Status.RUNNING, 7, timedelta(days=3), False),
            ("past_cadence_window_is_due", AutoresearchPipeline.Status.RUNNING, 7, timedelta(days=8), True),
            ("converged_overdue_is_due", AutoresearchPipeline.Status.CONVERGED, 1, timedelta(days=2), True),
            ("paused_is_excluded", AutoresearchPipeline.Status.PAUSED, 1, None, False),
        ]
    )
    def test_load_active_pipelines_honors_cadence(
        self,
        _name: str,
        status: str,
        cadence_days: int,
        scored_ago: Optional[timedelta],
        expected_due: bool,
    ) -> None:
        pipeline = self._create_pipeline(
            status=status,
            cadence_days=cadence_days,
            last_scored_at=timezone.now() - scored_ago if scored_ago else None,
        )
        result = activity_load_active_pipelines(LoadActivePipelinesInput())
        assert (str(pipeline.id) in [d.pipeline_id for d in result.due]) == expected_due

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
