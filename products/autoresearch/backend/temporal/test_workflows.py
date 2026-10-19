import uuid
import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import User

from products.autoresearch.backend.inference.person_property import CleanupOutcome
from products.autoresearch.backend.models import (
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchRun,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.query import BATCH_QUERY, SCORING_QUERY
from products.autoresearch.backend.temporal.workflows import (
    _VALIDATION_ATTEMPT_TIMEOUT,
    RESCUE_ITERATION_BUDGET,
    ActivePipeline,
    AutoresearchCoordinatorWorkflow,
    AutoresearchInferenceWorkflow,
    AutoresearchPropertyCleanupWorkflow,
    AutoresearchValidationWorkflow,
    CoordinatorWorkflowInput,
    FailCleanupRunInput,
    FailLostInferenceRunsInput,
    InferenceWorkflowResult,
    KickoffTrainingInput,
    KickoffTrainingResult,
    LoadActivePipelinesInput,
    LoadActivePipelinesResult,
    MarkDailySweepInput,
    PropertyCleanupWorkflowInput,
    PropertyCleanupWorkflowResult,
    RunInferenceInput,
    RunInferenceResult,
    RunShadowScoringInput,
    RunShadowScoringResult,
    RunValidationInput,
    RunValidationResult,
    ValidationWorkflowResult,
    activity_fail_lost_inference_runs,
    activity_kickoff_training,
    activity_load_active_pipelines,
    activity_mark_daily_sweep,
    activity_remove_person_property,
    activity_run_inference,
    activity_run_shadow_scoring,
    activity_run_validation,
    daily_sweep_key,
    evaluate_pipeline_outcome,
)
from products.autoresearch.backend.testing import TeamScopedTestMixin
from products.autoresearch.backend.training.artifacts import scored_persons_key


def _inference(status: str = "completed", error: Optional[str] = None) -> InferenceWorkflowResult:
    return InferenceWorkflowResult(run_id="run-1", rows_scored=10, status=status, error=error)


def _validation(status: str = "completed", error: Optional[str] = None) -> ValidationWorkflowResult:
    return ValidationWorkflowResult(dates_validated=1, total_rows=10, status=status, error=error)


def _kickoff(reason: str = "explore", error: Optional[str] = None) -> KickoffTrainingResult:
    return KickoffTrainingResult(kicked_off=reason == "explore", reason=reason, error=error)


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
            ("kickoff_skip_is_not_failure", _inference(), _validation(), _kickoff(reason="not_due"), True, 0),
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
        desktop = patch("products.autoresearch.backend.temporal.workflows.get_desktop_access_decision")
        desktop.start().return_value.allowed = True
        self.addCleanup(desktop.stop)
        usage = patch("products.autoresearch.backend.temporal.workflows.task_run_usage_limited", return_value=False)
        self.mock_usage_limited = usage.start()
        self.addCleanup(usage.stop)

    def _create_pipeline(self, **overrides: Any) -> AutoresearchPipeline:
        params: dict[str, Any] = {
            "team": self.team,
            "created_by": self.user,
            "name": "test pipeline",
            "target_event": "$pageview",
            "status": AutoresearchPipeline.Status.RUNNING,
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

    def test_load_active_pipelines_lists_pipelines_that_missed_yesterday_first(self) -> None:
        scored_yesterday = self._create_pipeline(last_scored_at=datetime(2026, 9, 10, 3, tzinfo=UTC))
        validates_only = self._create_pipeline(last_scored_at=datetime(2026, 9, 11, 3, tzinfo=UTC))
        missed_yesterday = self._create_pipeline(last_scored_at=datetime(2026, 9, 9, 3, tzinfo=UTC))
        never_scored = self._create_pipeline()

        result = activity_load_active_pipelines(LoadActivePipelinesInput())

        order = [p.pipeline_id for p in result.pipelines]
        assert set(order[:2]) == {str(missed_yesterday.id), str(never_scored.id)}
        assert set(order[2:]) == {str(scored_yesterday.id), str(validates_only.id)}

    @parameterized.expand(
        [
            ("creator_lost_access", True, True, {}),
            ("outside_the_rollout", False, False, {}),
            ("organization_deactivated", False, True, {"is_active": False}),
            ("organization_pending_deletion", False, True, {"is_pending_deletion": True}),
        ]
    )
    def test_load_active_pipelines_excludes_pipelines_it_cannot_run(
        self, _name: str, creator_lost_access: bool, in_rollout: bool, organization_fields: dict[str, bool]
    ) -> None:
        self.mock_access.return_value = in_rollout
        for field, value in organization_fields.items():
            setattr(self.organization, field, value)
        self.organization.save()
        if creator_lost_access:
            pipeline = self._create_pipeline(created_by=User.objects.create(email="left@example.com"))
        else:
            pipeline = self._create_pipeline()

        result = activity_load_active_pipelines(LoadActivePipelinesInput())

        assert str(pipeline.id) not in [p.pipeline_id for p in result.pipelines]
        pipeline.refresh_from_db()
        expected = AutoresearchPipeline.Status.PAUSED if creator_lost_access else AutoresearchPipeline.Status.RUNNING
        assert pipeline.status == expected

    @parameterized.expand(
        [
            ("inference_paused", "inference", AutoresearchPipeline.Status.PAUSED, True),
            ("validation_paused", "validation", AutoresearchPipeline.Status.PAUSED, True),
            ("inference_rollout_withdrawn", "inference", AutoresearchPipeline.Status.RUNNING, False),
            ("validation_rollout_withdrawn", "validation", AutoresearchPipeline.Status.RUNNING, False),
        ]
    )
    @patch("products.autoresearch.backend.temporal.workflows.run_online_validation_for_pipeline")
    @patch("products.autoresearch.backend.temporal.workflows.run_inference_for_pipeline")
    def test_activities_skip_a_pipeline_the_sweep_can_no_longer_run(
        self,
        _name: str,
        step: str,
        status: str,
        in_rollout: bool,
        mock_inference: MagicMock,
        mock_validation: MagicMock,
    ) -> None:
        pipeline = self._create_pipeline(status=status)
        self.mock_access.return_value = in_rollout

        result: RunInferenceResult | RunValidationResult
        env = ActivityEnvironment()
        if step == "inference":
            result = env.run(
                activity_run_inference,
                RunInferenceInput(pipeline_id=str(pipeline.id), team_id=self.team.id, prediction_date="2026-09-11"),
            )
        else:
            result = env.run(
                activity_run_validation, RunValidationInput(pipeline_id=str(pipeline.id), team_id=self.team.id)
            )

        assert result.status == "skipped"
        mock_inference.assert_not_called()
        mock_validation.assert_not_called()

    @parameterized.expand([("inference",), ("validation",)])
    @patch("products.autoresearch.backend.temporal.workflows.run_online_validation_for_pipeline", return_value=[])
    @patch("products.autoresearch.backend.temporal.workflows.run_inference_for_pipeline")
    def test_activities_run_their_queries_as_batch_work(
        self, step: str, mock_inference: MagicMock, mock_validation: MagicMock
    ) -> None:
        pipeline = self._create_pipeline()
        env = ActivityEnvironment()
        if step == "inference":
            AutoresearchModel.objects.create(
                pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION, model_recipe={"stub": True}, recipe_hash="abc"
            )
            mock_inference.return_value = MagicMock(pk="run-1", rows_scored=0, status="completed", error="")
            env.run(
                activity_run_inference,
                RunInferenceInput(pipeline_id=str(pipeline.id), team_id=self.team.id, prediction_date="2026-09-11"),
            )
            assert mock_inference.call_args.kwargs["query_context"] == SCORING_QUERY
            assert mock_inference.call_args.kwargs["scheduled"] is True
        else:
            env.run(activity_run_validation, RunValidationInput(pipeline_id=str(pipeline.id), team_id=self.team.id))
            assert mock_validation.call_args.kwargs["query_context"] == BATCH_QUERY
            claim_deadline = mock_validation.call_args.kwargs["claim_deadline"]
            assert django_timezone.now() < claim_deadline < django_timezone.now() + _VALIDATION_ATTEMPT_TIMEOUT

    @parameterized.expand(
        [
            ("first_pass_leaves_the_run_open", False, None, AutoresearchRun.Status.RUNNING, 5),
            ("retry_adds_to_the_failed_attempt", False, 2, AutoresearchRun.Status.RUNNING, 7),
            ("reconcile_pass_adds_to_the_first", True, 3, AutoresearchRun.Status.COMPLETED, 8),
        ]
    )
    @patch("products.autoresearch.backend.temporal.workflows.remove_output_person_property")
    def test_property_cleanup_run_stays_open_until_the_reconcile_pass(
        self,
        _name: str,
        final_pass: bool,
        cleared_before: int | None,
        expected_status: str,
        expected_cleared: int,
        mock_remove: MagicMock,
    ) -> None:
        pipeline = self._create_pipeline(output_person_property="predicted_p_pageview")
        run = AutoresearchRun.objects.create(
            pipeline=pipeline,
            run_type=AutoresearchRun.RunType.PROPERTY_CLEANUP,
            status=AutoresearchRun.Status.PENDING,
            rows_scored=cleared_before,
        )
        mock_remove.return_value = CleanupOutcome(persons_cleared=5)
        result = ActivityEnvironment().run(
            activity_remove_person_property,
            PropertyCleanupWorkflowInput(
                pipeline_id=str(pipeline.id),
                team_id=self.team.id,
                output_property="predicted_p_pageview",
                run_id=str(run.pk),
                final_pass=final_pass,
            ),
        )
        run.refresh_from_db()
        assert (run.status, run.rows_scored, result.persons_cleared) == (
            expected_status,
            expected_cleared,
            expected_cleared,
        )
        assert (run.completed_at is not None) == final_pass

    @parameterized.expand(
        [
            ("open_scheduled_row_is_reused", {}, True),
            ("other_date_is_not_reused", {"prediction_date": "2026-09-10"}, False),
            ("manual_row_is_not_reused", {"scheduled": False}, False),
            ("finished_row_is_not_reused", {"status": AutoresearchRun.Status.FAILED}, False),
            ("row_past_the_workflow_timeout_is_not_reused", {"age": timedelta(hours=6)}, False),
        ]
    )
    @patch("products.autoresearch.backend.temporal.workflows.run_inference_for_pipeline")
    def test_scheduled_retry_reuses_the_row_of_the_lost_attempt(
        self, _name: str, row: dict[str, Any], reused: bool, mock_inference: MagicMock
    ) -> None:
        pipeline = self._create_pipeline()
        AutoresearchModel.objects.create(
            pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION, model_recipe={"stub": True}, recipe_hash="abc"
        )
        earlier = AutoresearchRun.objects.create(
            pipeline=pipeline,
            run_type=AutoresearchRun.RunType.INFERENCE,
            scheduled=row.get("scheduled", True),
            status=row.get("status", AutoresearchRun.Status.RUNNING),
            started_at=django_timezone.now() - row.get("age", timedelta(minutes=10)),
            metrics={"prediction_date": row.get("prediction_date", "2026-09-11"), "horizon_days": 30},
        )
        mock_inference.return_value = MagicMock(pk="run-1", rows_scored=0, status="completed", error="")
        env = ActivityEnvironment()

        env.run(
            activity_run_inference,
            RunInferenceInput(pipeline_id=str(pipeline.id), team_id=self.team.id, prediction_date="2026-09-11"),
        )

        assert mock_inference.call_args.kwargs["run"] == (earlier if reused else None)
        assert mock_inference.call_args.kwargs["extra_metrics"] == {"workflow_run_id": env.info.workflow_run_id}

    @parameterized.expand(
        [
            ("paused", AutoresearchPipeline.Status.PAUSED),
            ("archived", AutoresearchPipeline.Status.ARCHIVED),
            ("run_deleted_with_its_pipeline", None),
        ]
    )
    def test_shadow_activity_that_skips_a_run_deletes_its_stored_people(
        self, _name: str, status: Optional[str]
    ) -> None:
        pipeline = self._create_pipeline()
        run = AutoresearchRun.objects.create(
            pipeline=pipeline,
            run_type=AutoresearchRun.RunType.INFERENCE,
            scheduled=True,
            status=AutoresearchRun.Status.COMPLETED,
            started_at=django_timezone.now() - timedelta(minutes=10),
            metrics={"prediction_date": "2026-09-11", "horizon_days": 30},
        )
        key = scored_persons_key(team_id=self.team.id, pipeline_id=str(pipeline.id), inference_run_id=str(run.pk))
        AutoresearchRun.objects.filter(pk=run.pk).update(metrics={**run.metrics, "scored_persons_key": key})
        if status is None:
            AutoresearchRun.objects.filter(pk=run.pk).delete()
        else:
            AutoresearchPipeline.objects.filter(pk=pipeline.pk).update(status=status)

        with patch("products.autoresearch.backend.inference.scoring.delete_scored_persons") as delete:
            result = ActivityEnvironment().run(
                activity_run_shadow_scoring,
                RunShadowScoringInput(pipeline_id=str(pipeline.id), team_id=self.team.id, run_id=str(run.pk)),
            )

        assert result.status == "skipped"
        delete.assert_called_once_with(key)

    def test_load_active_pipelines_fails_inference_runs_left_running(self) -> None:
        pipeline = self._create_pipeline()

        def _running(age: timedelta) -> AutoresearchRun:
            return AutoresearchRun.objects.create(
                pipeline=pipeline,
                run_type=AutoresearchRun.RunType.INFERENCE,
                scheduled=True,
                status=AutoresearchRun.Status.RUNNING,
                started_at=django_timezone.now() - age,
                metrics={"prediction_date": "2026-09-10", "horizon_days": 30},
            )

        lost = _running(timedelta(hours=6))
        live = _running(timedelta(hours=1))

        activity_load_active_pipelines(LoadActivePipelinesInput())

        lost.refresh_from_db()
        live.refresh_from_db()
        assert lost.status == AutoresearchRun.Status.FAILED
        assert lost.completed_at is not None
        assert lost.metrics["failure_kind"] == "other"
        assert live.status == AutoresearchRun.Status.RUNNING

    def test_fail_lost_inference_runs_closes_only_the_scheduled_runs_of_the_date(self) -> None:
        pipeline = self._create_pipeline()

        def _running(
            prediction_date: str, scheduled: bool = True, workflow_run_id: str = "daily-run"
        ) -> AutoresearchRun:
            return AutoresearchRun.objects.create(
                pipeline=pipeline,
                run_type=AutoresearchRun.RunType.INFERENCE,
                scheduled=scheduled,
                status=AutoresearchRun.Status.RUNNING,
                started_at=django_timezone.now() - timedelta(minutes=10),
                metrics={"prediction_date": prediction_date, "horizon_days": 30, "workflow_run_id": workflow_run_id},
            )

        lost = _running("2026-09-11")
        manual = _running("2026-09-11", scheduled=False)
        other_date = _running("2026-09-12")
        catch_up = _running("2026-09-11", workflow_run_id="catch-up-run")

        ActivityEnvironment().run(
            activity_fail_lost_inference_runs,
            FailLostInferenceRunsInput(
                pipeline_id=str(pipeline.id),
                team_id=self.team.id,
                prediction_date="2026-09-11",
                workflow_run_id="daily-run",
            ),
        )

        for run in (lost, manual, other_date, catch_up):
            run.refresh_from_db()
        assert (lost.status, lost.metrics["failure_kind"]) == (AutoresearchRun.Status.FAILED, "other")
        assert lost.completed_at is not None
        assert manual.status == AutoresearchRun.Status.RUNNING
        assert other_date.status == AutoresearchRun.Status.RUNNING
        assert catch_up.status == AutoresearchRun.Status.RUNNING

    @parameterized.expand(
        [
            ("lost_run_is_retried", [("failed", "other")], None, True, None),
            ("not_reached_by_the_daily_sweep_is_skipped", [], None, False, None),
            (
                "scored_today_is_skipped",
                [("failed", "other"), ("completed", None)],
                datetime(2026, 9, 11, 3),
                False,
                None,
            ),
            ("still_running_is_skipped", [("failed", "other"), ("running", None)], None, False, None),
            ("repeatable_failure_is_skipped", [("failed", "query_failed")], None, False, None),
            ("not_due_is_skipped", [("failed", "other")], datetime(2026, 9, 11, 1), False, None),
            ("deferred_while_the_daily_sweep_runs", [("failed", "other")], None, False, "running"),
            ("runs_once_the_daily_sweep_is_done", [("failed", "other")], None, True, "done"),
        ]
    )
    def test_catch_up_discovery_lists_only_pipelines_whose_run_was_lost(
        self,
        _name: str,
        runs: list[tuple[str, Optional[str]]],
        scored_at: Optional[datetime],
        listed: bool,
        daily_sweep: Optional[str],
    ) -> None:
        pipeline = self._create_pipeline(last_scored_at=scored_at.replace(tzinfo=UTC) if scored_at else None)
        if daily_sweep is not None:
            ActivityEnvironment().run(
                activity_mark_daily_sweep, MarkDailySweepInput(run_date="2026-09-11", state=daily_sweep)
            )
            self.addCleanup(cache.delete, daily_sweep_key("2026-09-11"))
        for index, (status, failure_kind) in enumerate(runs):
            run = AutoresearchRun.objects.create(
                pipeline=pipeline,
                run_type=AutoresearchRun.RunType.INFERENCE,
                scheduled=True,
                status=status,
                started_at=django_timezone.now() - timedelta(hours=2),
                metrics={"prediction_date": "2026-09-11", "horizon_days": 30, "failure_kind": failure_kind},
            )
            AutoresearchRun.objects.filter(pk=run.pk).update(
                created_at=django_timezone.now() - timedelta(hours=3) + timedelta(minutes=index)
            )

        result = activity_load_active_pipelines(LoadActivePipelinesInput(catch_up_date="2026-09-11"))

        assert [p.pipeline_id for p in result.pipelines] == ([str(pipeline.id)] if listed else [])

    @parameterized.expand([("scheduled", False), ("manual", True)])
    @patch("products.autoresearch.backend.temporal.workflows.run_inference_for_pipeline")
    def test_inference_refuses_a_deleted_action_target(
        self, _name: str, manual: bool, mock_inference: MagicMock
    ) -> None:
        pipeline = self._create_pipeline(target_definition={"type": "action", "action_id": 999999})
        AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            model_recipe={"stub": True},
            recipe_hash="abc123",
            holdout_score=0.75,
        )
        run = (
            AutoresearchRun.objects.create(
                pipeline=pipeline,
                run_type=AutoresearchRun.RunType.INFERENCE,
                status=AutoresearchRun.Status.RUNNING,
            )
            if manual
            else None
        )

        with self.assertRaises(ApplicationError):
            ActivityEnvironment().run(
                activity_run_inference,
                RunInferenceInput(
                    pipeline_id=str(pipeline.id),
                    team_id=self.team.id,
                    prediction_date="2026-09-11",
                    run_id=str(run.id) if run else None,
                    user_id=self.user.id if run else None,
                ),
            )
        mock_inference.assert_not_called()
        if run is not None:
            run.refresh_from_db()
            assert run.status == AutoresearchRun.Status.FAILED
            assert "cannot be resolved" in run.error

    @patch("products.autoresearch.backend.temporal.workflows.run_training")
    def test_kickoff_passes_pipeline_creator_to_training(self, mock_run_training: MagicMock) -> None:
        pipeline = self._create_pipeline()

        result = activity_kickoff_training(KickoffTrainingInput(pipeline_id=str(pipeline.id), team_id=self.team.id))

        assert result.kicked_off
        mock_run_training.assert_called_once()
        assert mock_run_training.call_args.kwargs["user_id"] == self.user.id

    @patch("products.autoresearch.backend.temporal.workflows.run_training")
    def test_kickoff_without_creator_fails_loudly(self, mock_run_training: MagicMock) -> None:
        pipeline = self._create_pipeline(created_by=None)

        result = activity_kickoff_training(KickoffTrainingInput(pipeline_id=str(pipeline.id), team_id=self.team.id))

        assert not result.kicked_off
        assert result.reason == "no_creator"
        assert result.error
        mock_run_training.assert_not_called()

    @parameterized.expand(
        [
            ("pending_run", AutoresearchTrainingRun.Status.PENDING, False, True, True, "already_running"),
            ("run_ended_today", AutoresearchTrainingRun.Status.COMPLETED, False, True, True, "already_ran_today"),
            ("tasks_usage_limited", None, True, True, True, "tasks_gated"),
            ("rollout_withdrawn_since_discovery", None, False, False, True, "tasks_gated"),
            ("organization_deactivated_since_discovery", None, False, True, False, "tasks_gated"),
        ]
    )
    @patch("products.autoresearch.backend.temporal.workflows.run_training")
    def test_kickoff_skips(
        self,
        _name: str,
        run_status: Optional[str],
        usage_limited: bool,
        in_rollout: bool,
        organization_active: bool,
        expected_reason: str,
        mock_run_training: MagicMock,
    ) -> None:
        pipeline = self._create_pipeline()
        if run_status:
            AutoresearchTrainingRun.objects.create(pipeline=pipeline, status=run_status, iteration_budget=10)
        self.mock_usage_limited.return_value = usage_limited
        self.mock_access.return_value = in_rollout
        self.organization.is_active = organization_active
        self.organization.save()

        result = activity_kickoff_training(KickoffTrainingInput(pipeline_id=str(pipeline.id), team_id=self.team.id))

        assert result.reason == expected_reason
        mock_run_training.assert_not_called()

    @parameterized.expand(
        [
            ("new_pipeline_explores", 7, [], False, "explore"),
            (
                "promoting_runs_keep_exploring",
                7,
                [("explore", "completed", True, 9), ("explore", "completed", True, 10)],
                False,
                "explore",
            ),
            (
                "rescue_runs_do_not_end_the_burst",
                7,
                [*[("explore", "failed", None, d) for d in (5, 6, 7, 8)], ("rescue", "completed", False, 10)],
                False,
                "explore",
            ),
            ("explore_takes_precedence_over_rescue", 7, [], True, "explore"),
            ("non_promoting_run_ends_the_burst", 7, [("explore", "completed", False, 10)], False, "not_due"),
            (
                "five_runs_end_the_burst_then_interval_passes",
                7,
                [(None, "failed", None, d) for d in (0, 1, 2, 3, 4)],
                False,
                "scheduled",
            ),
            ("maintain_within_interval", 14, [(None, "failed", None, d) for d in (1, 2, 3, 4, 5)], False, "not_due"),
            (
                "manual_run_resets_the_clock",
                7,
                [("scheduled", "completed", False, -30), ("manual", "completed", True, 5)],
                False,
                "not_due",
            ),
            ("only_when_asked", None, [], False, "manual_only"),
            ("only_when_asked_still_rescues", None, [], True, "rescue_unscorable"),
            (
                "not_due_rescues_an_unscorable_champion",
                7,
                [("explore", "completed", False, 8)],
                True,
                "rescue_unscorable",
            ),
            ("rescue_ran_yesterday", None, [("rescue", "failed", None, 10)], True, "rescue_throttled"),
        ]
    )
    @patch("products.autoresearch.backend.temporal.workflows.run_training")
    def test_kickoff_follows_the_research_schedule(
        self,
        _name: str,
        research_interval_days: Optional[int],
        prior_runs: list[tuple[Optional[str], str, Optional[bool], int]],
        unscorable: bool,
        expected_reason: str,
        mock_run_training: MagicMock,
    ) -> None:
        with time_machine.travel(datetime(2026, 8, 1, tzinfo=UTC), tick=False):
            pipeline = self._create_pipeline(research_interval_days=research_interval_days, iterations_per_run=8)
        champion = AutoresearchModel.objects.create(
            pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION, model_recipe={"stub": True}, recipe_hash="abc"
        )
        for prediction_date in ("2026-09-09", "2026-09-10"):
            AutoresearchRun.objects.create(
                pipeline=pipeline,
                model=champion,
                run_type=AutoresearchRun.RunType.INFERENCE,
                scheduled=True,
                status=AutoresearchRun.Status.FAILED if unscorable else AutoresearchRun.Status.COMPLETED,
                metrics={"prediction_date": prediction_date, "failure_kind": "limit_exceeded"} if unscorable else {},
            )
        # The day of each prior run is a day of September 2026; a value below 1 counts back into August.
        for kickoff_reason, run_status, promoted, day in prior_runs:
            with time_machine.travel(datetime(2026, 9, 1, 2, tzinfo=UTC) + timedelta(days=day - 1), tick=False):
                AutoresearchTrainingRun.objects.create(
                    pipeline=pipeline,
                    status=run_status,
                    kickoff_reason=kickoff_reason,
                    iteration_budget=3,
                    summary={} if promoted is None else {"champion_promoted": promoted},
                )

        with time_machine.travel(datetime(2026, 9, 11, 2, tzinfo=UTC), tick=False):
            result = activity_kickoff_training(KickoffTrainingInput(pipeline_id=str(pipeline.id), team_id=self.team.id))

        assert result.reason == expected_reason
        if expected_reason in ("explore", "scheduled", "rescue_unscorable"):
            assert result.kicked_off
            kwargs = mock_run_training.call_args.kwargs
            rescue = expected_reason == "rescue_unscorable"
            assert kwargs["iteration_budget"] == (RESCUE_ITERATION_BUDGET if rescue else 8)
            assert kwargs["rescue"] is rescue
            assert kwargs["kickoff_reason"] == ("rescue" if rescue else expected_reason)
        else:
            assert not result.kicked_off
            mock_run_training.assert_not_called()

    @parameterized.expand([("transient_failure_raises", RuntimeError("boom")), ("refused_launch", ValueError("left"))])
    @patch("products.autoresearch.backend.temporal.workflows.run_training")
    def test_failed_launch(self, _name: str, error: Exception, mock_run_training: MagicMock) -> None:
        pipeline = self._create_pipeline()
        mock_run_training.side_effect = error

        if isinstance(error, RuntimeError):
            with self.assertRaises(RuntimeError):
                activity_kickoff_training(KickoffTrainingInput(pipeline_id=str(pipeline.id), team_id=self.team.id))
        else:
            result = activity_kickoff_training(KickoffTrainingInput(pipeline_id=str(pipeline.id), team_id=self.team.id))
            assert result.reason == "not_launchable"


@pytest.mark.parametrize(
    "first_pass,expected_passes,expected_failed_run",
    [
        ("finishes", [False, True], None),
        ("stops", [False], None),
        ("fails", [False], "run-1"),
    ],
)
async def test_property_cleanup_workflow_reconciles_and_fails_the_run(
    first_pass: str, expected_passes: list[bool], expected_failed_run: str | None
) -> None:
    passes: list[bool] = []
    failed_runs: list[str] = []

    @activity.defn(name="autoresearch-property-cleanup.remove_person_property")
    async def remove(inp: PropertyCleanupWorkflowInput) -> PropertyCleanupWorkflowResult:
        passes.append(inp.final_pass)
        if first_pass == "fails":
            raise ApplicationError("capture is down", non_retryable=True)
        stopped = "reenabled" if first_pass == "stops" else None
        return PropertyCleanupWorkflowResult(persons_cleared=1, status="completed", stopped=stopped)

    @activity.defn(name="autoresearch-property-cleanup.fail_run")
    async def fail_run(inp: FailCleanupRunInput) -> None:
        failed_runs.append(inp.run_id)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="cleanup-test",
            workflows=[AutoresearchPropertyCleanupWorkflow],
            activities=[remove, fail_run],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                AutoresearchPropertyCleanupWorkflow.run,
                PropertyCleanupWorkflowInput(pipeline_id="p", team_id=1, output_property="score", run_id="run-1"),
                id=str(uuid.uuid4()),
                task_queue="cleanup-test",
            )
            if first_pass == "fails":
                with pytest.raises(WorkflowFailureError):
                    await handle.result()
            else:
                await handle.result()

    assert passes == expected_passes
    assert failed_runs == ([expected_failed_run] if expected_failed_run else [])


async def test_coordinator_bounds_the_sweep_and_scores_shadows_after_every_champion() -> None:
    pipeline_ids = [f"p{i}" for i in range(5)]
    in_flight = 0
    max_in_flight = 0
    events: list[tuple[str, str]] = []
    inference_inputs: list[RunInferenceInput] = []

    async def heavy_step(name: str, pipeline_id: str) -> None:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        events.append((name, pipeline_id))

    @activity.defn(name="autoresearch-coordinator.load_active_pipelines")
    async def load(inp: LoadActivePipelinesInput) -> LoadActivePipelinesResult:
        return LoadActivePipelinesResult(
            pipelines=[ActivePipeline(pipeline_id=pid, team_id=1, score_due=True) for pid in pipeline_ids]
        )

    @activity.defn(name="autoresearch-inference.run_inference")
    async def infer(inp: RunInferenceInput) -> RunInferenceResult:
        inference_inputs.append(inp)
        await heavy_step("champion", inp.pipeline_id)
        return RunInferenceResult(run_id=f"run-{inp.pipeline_id}", rows_scored=1, status="completed")

    @activity.defn(name="autoresearch-validation.run_validation")
    async def validate(inp: RunValidationInput) -> RunValidationResult:
        await heavy_step("validation", inp.pipeline_id)
        return RunValidationResult(dates_validated=1, total_rows=1, status="completed")

    @activity.defn(name="autoresearch-coordinator.kickoff_training")
    async def kickoff(inp: KickoffTrainingInput) -> KickoffTrainingResult:
        return KickoffTrainingResult(kicked_off=False, reason="not_due")

    @activity.defn(name="autoresearch-coordinator.mark_daily_sweep")
    async def mark(inp: MarkDailySweepInput) -> None:
        events.append(("mark", inp.state))

    @activity.defn(name="autoresearch-coordinator.run_shadow_scoring")
    async def shadows(inp: RunShadowScoringInput) -> RunShadowScoringResult:
        assert inp.run_id == f"run-{inp.pipeline_id}"
        events.append(("shadow", inp.pipeline_id))
        if inp.pipeline_id == "p0":
            raise ApplicationError("predict sandbox died", non_retryable=True)
        return RunShadowScoringResult(completed=1, failed=0, skipped=0, status="completed")

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="coordinator-test",
            workflows=[AutoresearchCoordinatorWorkflow, AutoresearchInferenceWorkflow, AutoresearchValidationWorkflow],
            activities=[load, infer, validate, kickoff, shadows, mark],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                AutoresearchCoordinatorWorkflow.run,
                CoordinatorWorkflowInput(run_date="2026-10-18", max_concurrency=2),
                id=str(uuid.uuid4()),
                task_queue="coordinator-test",
            )

    assert max_in_flight == 2
    # The daily sweep stays marked running until its last validation and shadow phase ends.
    assert (events[0], events[-1]) == (("mark", "running"), ("mark", "done"))
    first_shadow = next(index for index, (name, _) in enumerate(events) if name == "shadow")
    assert {pid for name, pid in events[:first_shadow] if name == "champion"} == set(pipeline_ids)
    assert sorted(pid for name, pid in events if name == "shadow") == pipeline_ids
    assert all(inp.defer_shadows and inp.coordinator_concurrency == 2 for inp in inference_inputs)
    # A shadow failure leaves the champion's pipeline counted as processed.
    assert (result.pipelines_processed, result.pipelines_errored, result.status) == (5, 0, "completed")


@pytest.mark.parametrize("catch_up", [False, True])
async def test_coordinator_fails_the_runs_of_a_failed_inference_child(catch_up: bool) -> None:
    load_inputs: list[LoadActivePipelinesInput] = []
    failed_runs: list[FailLostInferenceRunsInput] = []
    steps: list[str] = []

    @activity.defn(name="autoresearch-coordinator.load_active_pipelines")
    async def load(inp: LoadActivePipelinesInput) -> LoadActivePipelinesResult:
        load_inputs.append(inp)
        return LoadActivePipelinesResult(
            pipelines=[ActivePipeline(pipeline_id=pid, team_id=1, score_due=True) for pid in ("lost", "scored")]
        )

    @activity.defn(name="autoresearch-inference.run_inference")
    async def infer(inp: RunInferenceInput) -> RunInferenceResult:
        if inp.pipeline_id == "lost":
            raise ApplicationError("worker lost", non_retryable=True)
        return RunInferenceResult(run_id=f"run-{inp.pipeline_id}", rows_scored=1, status="completed")

    @activity.defn(name="autoresearch-coordinator.fail_lost_inference_runs")
    async def fail_lost(inp: FailLostInferenceRunsInput) -> int:
        failed_runs.append(inp)
        return 1

    @activity.defn(name="autoresearch-coordinator.mark_daily_sweep")
    async def mark(inp: MarkDailySweepInput) -> None:
        steps.append(f"mark-{inp.state}")

    @activity.defn(name="autoresearch-validation.run_validation")
    async def validate(inp: RunValidationInput) -> RunValidationResult:
        steps.append("validation")
        return RunValidationResult(dates_validated=1, total_rows=1, status="completed")

    @activity.defn(name="autoresearch-coordinator.kickoff_training")
    async def kickoff(inp: KickoffTrainingInput) -> KickoffTrainingResult:
        steps.append("kickoff")
        return KickoffTrainingResult(kicked_off=False, reason="not_due")

    @activity.defn(name="autoresearch-coordinator.run_shadow_scoring")
    async def shadows(inp: RunShadowScoringInput) -> RunShadowScoringResult:
        steps.append(f"shadow-{inp.pipeline_id}")
        return RunShadowScoringResult(completed=1, failed=0, skipped=0, status="completed")

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="coordinator-test",
            workflows=[AutoresearchCoordinatorWorkflow, AutoresearchInferenceWorkflow, AutoresearchValidationWorkflow],
            activities=[load, infer, fail_lost, validate, kickoff, shadows, mark],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                AutoresearchCoordinatorWorkflow.run,
                CoordinatorWorkflowInput(run_date="2026-10-18", catch_up=catch_up),
                id=str(uuid.uuid4()),
                task_queue="coordinator-test",
            )

    assert load_inputs == [LoadActivePipelinesInput(catch_up_date="2026-10-18" if catch_up else None)]
    assert [replace(inp, workflow_run_id=None) for inp in failed_runs] == [
        FailLostInferenceRunsInput(pipeline_id="lost", team_id=1, prediction_date="2026-10-18")
    ]
    # Cleanup is scoped to the failed child's execution, so a catch-up child's live row stays open.
    assert failed_runs[0].workflow_run_id
    assert (result.pipelines_processed, result.pipelines_errored) == (1, 1)
    assert "shadow-scored" in steps
    # The daily sweep already kicked off training and validated, so a catch-up only scores.
    assert ("kickoff" in steps, "validation" in steps) == (not catch_up, not catch_up)
    assert [step for step in steps if step.startswith("mark-")] == ([] if catch_up else ["mark-running", "mark-done"])
