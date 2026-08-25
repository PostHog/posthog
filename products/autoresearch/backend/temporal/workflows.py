"""
Temporal workflows for autoresearch inference and online validation.

Both workflows are regular Temporal workflows (not TaskRun/agent sandboxes) because
scoring and validation are deterministic pipelines. Training runs through Task/TaskRun.

Activities are synchronous — Temporal runs them in a thread pool, which is correct
for Django ORM + HogQL queries. Workflows are async and only orchestrate activities.
"""

from __future__ import annotations

from dataclasses import field
from datetime import date, timedelta
from typing import Optional

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    import asyncio as _asyncio

    from django.db import transaction
    from django.db.models import F
    from django.utils import timezone as django_timezone

    from products.autoresearch.backend.evaluation.online_validation import run_online_validation_for_pipeline
    from products.autoresearch.backend.inference.scoring import run_inference_for_pipeline
    from products.autoresearch.backend.models import (
        AutoresearchModel,
        AutoresearchPipeline,
        AutoresearchRun,
        AutoresearchTrainingRun,
    )
    from products.autoresearch.backend.training.runner import run_training

from posthog.dataclasses import frozen
from posthog.models.scoping import team_scope
from posthog.temporal.common.base import PostHogWorkflow

logger = structlog.get_logger(__name__)


# ── I/O dataclasses ──────────────────────────────────────────────────────────


@frozen
class InferenceWorkflowInput:
    pipeline_id: str
    team_id: int
    prediction_date: str  # ISO date string, e.g. "2026-05-26"


@frozen
class InferenceWorkflowResult:
    run_id: str
    rows_scored: int
    status: str
    error: Optional[str] = None


@frozen
class LoadChampionInput:
    pipeline_id: str
    team_id: int


@frozen
class LoadChampionResult:
    model_id: str


@frozen
class RunInferenceInput:
    pipeline_id: str
    team_id: int
    model_id: str
    prediction_date: str  # ISO date string


@frozen
class RunInferenceResult:
    run_id: str
    rows_scored: int
    status: str
    error: Optional[str] = None


# ── Activities ───────────────────────────────────────────────────────────────


@activity.defn(name="autoresearch-inference.load_champion")
def activity_load_champion(inp: LoadChampionInput) -> LoadChampionResult:
    """Load the champion model for a pipeline. Raises if none exists."""
    with team_scope(inp.team_id):
        pipeline = AutoresearchPipeline.objects.get(pk=inp.pipeline_id)
        champion = (
            AutoresearchModel.objects.filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
            .order_by("-created_at")
            .first()
        )
    if not champion:
        raise ValueError(f"No champion model for pipeline {inp.pipeline_id}")
    return LoadChampionResult(model_id=str(champion.pk))


@activity.defn(name="autoresearch-inference.run_inference")
def activity_run_inference(inp: RunInferenceInput) -> RunInferenceResult:
    """Score the inference population and emit autoresearch_prediction events."""
    with team_scope(inp.team_id):
        pipeline = AutoresearchPipeline.objects.select_related("team").get(pk=inp.pipeline_id)
        model = AutoresearchModel.objects.get(pk=inp.model_id)
        run = run_inference_for_pipeline(
            pipeline=pipeline, model=model, prediction_date=date.fromisoformat(inp.prediction_date)
        )
    return RunInferenceResult(
        run_id=str(run.pk),
        rows_scored=run.rows_scored or 0,
        status=run.status,
        error=run.error or None,
    )


# ── Workflow ─────────────────────────────────────────────────────────────────

# Load champion is a cheap DB read; score can take minutes for large populations.
_LOAD_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5))
_SCORE_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=30))


@workflow.defn(name="autoresearch-inference")
class AutoresearchInferenceWorkflow(PostHogWorkflow):
    """
    Temporal workflow that runs daily inference for one autoresearch pipeline.

    Steps:
    1. Load the champion model for the pipeline.
    2. Score the inference population and emit autoresearch_prediction events.

    Both steps delegate to products.autoresearch.backend.inference.scoring so the same
    code is exercised by both the Temporal workflow and the local management
    command (autoresearch_score).
    """

    inputs_cls = InferenceWorkflowInput

    @workflow.run
    async def run(self, inp: InferenceWorkflowInput) -> InferenceWorkflowResult:
        workflow.logger.info(
            "autoresearch_inference_workflow_start",
            pipeline_id=inp.pipeline_id,
            prediction_date=inp.prediction_date,
        )

        champion = await workflow.execute_activity(
            activity_load_champion,
            LoadChampionInput(pipeline_id=inp.pipeline_id, team_id=inp.team_id),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=_LOAD_RETRY,
        )

        result = await workflow.execute_activity(
            activity_run_inference,
            RunInferenceInput(
                pipeline_id=inp.pipeline_id,
                team_id=inp.team_id,
                model_id=champion.model_id,
                prediction_date=inp.prediction_date,
            ),
            start_to_close_timeout=timedelta(hours=2),
            retry_policy=_SCORE_RETRY,
        )

        workflow.logger.info(
            "autoresearch_inference_workflow_complete",
            pipeline_id=inp.pipeline_id,
            run_id=result.run_id,
            rows_scored=result.rows_scored,
            status=result.status,
        )

        return InferenceWorkflowResult(
            run_id=result.run_id,
            rows_scored=result.rows_scored,
            status=result.status,
            error=result.error,
        )


# ── Validation workflow I/O ───────────────────────────────────────────────────


@frozen
class ValidationWorkflowInput:
    pipeline_id: str
    team_id: int


@frozen
class ValidationWorkflowResult:
    dates_validated: int
    total_rows: int
    status: str
    error: Optional[str] = None


@frozen
class RunValidationInput:
    pipeline_id: str
    team_id: int


@frozen
class RunValidationResult:
    dates_validated: int
    total_rows: int
    status: str
    error: Optional[str] = None


# ── Validation activities ─────────────────────────────────────────────────────

# Validation does all its work (HogQL + sklearn) inside a single activity to
# keep the Temporal payload small — we only return summary counts, not raw data.
_VALIDATION_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=30))


@activity.defn(name="autoresearch-validation.run_validation")
def activity_run_validation(inp: RunValidationInput) -> RunValidationResult:
    """Find all matured unvalidated prediction dates and validate each one."""
    with team_scope(inp.team_id):
        pipeline = AutoresearchPipeline.objects.select_related("team").get(pk=inp.pipeline_id)
        runs = run_online_validation_for_pipeline(pipeline)
    # A per-date failure is recorded on its own run rather than raised, so inspect the
    # statuses here. Reporting completed regardless would leave the retry policy unused
    # even when every matured date failed; the coordinator isolates the failure per
    # pipeline (it gathers with return_exceptions=True).
    failed = [r for r in runs if r.status == AutoresearchRun.Status.FAILED]
    if failed:
        raise ApplicationError(
            f"{len(failed)} of {len(runs)} validation dates failed: "
            + "; ".join(str(r.error or "unknown")[:200] for r in failed[:3])
        )
    return RunValidationResult(
        dates_validated=len(runs),
        total_rows=sum(r.rows_scored or 0 for r in runs),
        status="completed",
    )


# ── Validation workflow ───────────────────────────────────────────────────────


@workflow.defn(name="autoresearch-validation")
class AutoresearchValidationWorkflow(PostHogWorkflow):
    """
    Temporal workflow that runs online validation for one autoresearch pipeline.

    Triggered daily (same cadence as inference) after inference has emitted
    predictions. Finds all matured, unvalidated prediction dates and computes
    realized AUC / Brier / ECE / lift@k per model. Updates AutoresearchModel
    realized_score, calibration_error, and is_preliminary in Postgres.
    """

    inputs_cls = ValidationWorkflowInput

    @workflow.run
    async def run(self, inp: ValidationWorkflowInput) -> ValidationWorkflowResult:
        workflow.logger.info(
            "autoresearch_validation_workflow_start",
            pipeline_id=inp.pipeline_id,
        )

        result = await workflow.execute_activity(
            activity_run_validation,
            RunValidationInput(pipeline_id=inp.pipeline_id, team_id=inp.team_id),
            start_to_close_timeout=timedelta(hours=1),
            retry_policy=_VALIDATION_RETRY,
        )

        workflow.logger.info(
            "autoresearch_validation_workflow_complete",
            pipeline_id=inp.pipeline_id,
            dates_validated=result.dates_validated,
            total_rows=result.total_rows,
            status=result.status,
        )

        return ValidationWorkflowResult(
            dates_validated=result.dates_validated,
            total_rows=result.total_rows,
            status=result.status,
            error=result.error,
        )


# ── Coordinator workflow I/O ──────────────────────────────────────────────────


@frozen
class CoordinatorWorkflowInput:
    # ISO date string; if omitted the workflow uses workflow.now()
    run_date: Optional[str] = None


@frozen
class CoordinatorWorkflowResult:
    pipelines_processed: int
    pipelines_errored: int
    status: str


@frozen
class LoadActivePipelinesInput:
    pass


@frozen
class DuePipeline:
    pipeline_id: str
    team_id: int


@frozen
class LoadActivePipelinesResult:
    due: list[DuePipeline]


@frozen
class KickoffTrainingInput:
    pipeline_id: str
    team_id: int


@frozen
class PipelineRunOutcome:
    pipeline_id: str
    succeeded: bool
    errors: list[str] = field(default_factory=list)


def evaluate_pipeline_outcome(
    pipeline_id: str,
    inference: InferenceWorkflowResult | BaseException,
    validation: ValidationWorkflowResult | BaseException,
    kickoff: KickoffTrainingResult | BaseException,
) -> PipelineRunOutcome:
    """Classify one pipeline's step results, treating soft-failed activity results as failures too."""
    errors: list[str] = []

    if isinstance(inference, BaseException):
        errors.append(f"inference: {inference}")
    elif inference.status == "failed":
        errors.append(f"inference: {inference.error or 'failed'}")

    if isinstance(validation, BaseException):
        errors.append(f"validation: {validation}")
    elif validation.status == "failed":
        errors.append(f"validation: {validation.error or 'failed'}")

    if isinstance(kickoff, BaseException):
        errors.append(f"training kickoff: {kickoff}")
    elif kickoff.error:
        errors.append(f"training kickoff ({kickoff.reason}): {kickoff.error}")

    return PipelineRunOutcome(pipeline_id=pipeline_id, succeeded=not errors, errors=errors)


@frozen
class KickoffTrainingResult:
    kicked_off: bool
    reason: str  # "started" | "budget_exhausted" | "already_running" | "not_eligible" | "no_creator" | "error"
    error: Optional[str] = None


# ── Coordinator activities ────────────────────────────────────────────────────

_COORDINATOR_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5))
_KICKOFF_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=10))


@activity.defn(name="autoresearch-coordinator.load_active_pipelines")
def activity_load_active_pipelines(inp: LoadActivePipelinesInput) -> LoadActivePipelinesResult:
    """Return the pipelines that are due for scoring per their cadence, across every team."""
    now = django_timezone.now()
    # unscoped() because the coordinator's job is exactly to sweep every team. The
    # pipelines it returns carry their team so the downstream activities can scope.
    candidates = (
        AutoresearchPipeline.objects.unscoped()
        .filter(status__in=[AutoresearchPipeline.Status.RUNNING, AutoresearchPipeline.Status.CONVERGED])
        .values("id", "team_id", "cadence_days", "last_scored_at")
    )
    due = [
        DuePipeline(pipeline_id=str(row["id"]), team_id=row["team_id"])
        for row in candidates
        if row["last_scored_at"] is None or row["last_scored_at"] + timedelta(days=row["cadence_days"]) <= now
    ]
    return LoadActivePipelinesResult(due=due)


@activity.defn(name="autoresearch-coordinator.kickoff_training")
def activity_kickoff_training(inp: KickoffTrainingInput) -> KickoffTrainingResult:
    """Deduct iteration budget and fire a new agent training run if eligible."""
    daily_budget: int = 0
    try:
        with team_scope(inp.team_id), transaction.atomic():
            pipeline = AutoresearchPipeline.objects.select_for_update().get(pk=inp.pipeline_id)

            if pipeline.status != AutoresearchPipeline.Status.RUNNING:
                return KickoffTrainingResult(kicked_off=False, reason="not_eligible")

            if pipeline.iteration_budget_remaining <= 0:
                return KickoffTrainingResult(kicked_off=False, reason="budget_exhausted")

            if AutoresearchTrainingRun.objects.filter(
                pipeline=pipeline,
                status=AutoresearchTrainingRun.Status.RUNNING,
            ).exists():
                return KickoffTrainingResult(kicked_off=False, reason="already_running")

            # Training runs in a Tasks sandbox that requires a real owning user. CLI-created
            # pipelines have no creator, so fail before spending budget rather than launching
            # a run that would crash in the tasks facade.
            if pipeline.created_by_id is None:
                error = (
                    f"Pipeline {inp.pipeline_id} has no creator; training kickoff requires created_by to own the task"
                )
                logger.error(
                    "autoresearch_kickoff_training_no_creator",
                    pipeline_id=inp.pipeline_id,
                )
                return KickoffTrainingResult(kicked_off=False, reason="no_creator", error=error)

            daily_budget = min(10, pipeline.iteration_budget_remaining)
            pipeline.iteration_budget_remaining -= daily_budget
            pipeline.save(update_fields=["iteration_budget_remaining"])

        with team_scope(inp.team_id):
            run_training(pipeline=pipeline, iteration_budget=daily_budget, user_id=pipeline.created_by_id)
        return KickoffTrainingResult(kicked_off=True, reason="started")

    except Exception as exc:
        if daily_budget > 0:
            # Re-add the budget since the training launch failed.
            with team_scope(inp.team_id):
                AutoresearchPipeline.objects.filter(pk=inp.pipeline_id).update(
                    iteration_budget_remaining=F("iteration_budget_remaining") + daily_budget
                )
        return KickoffTrainingResult(kicked_off=False, reason="error", error=str(exc))


# ── Coordinator workflow ──────────────────────────────────────────────────────


@workflow.defn(name="autoresearch-coordinator")
class AutoresearchCoordinatorWorkflow(PostHogWorkflow):
    """
    Daily coordinator that fans out inference, validation, and training kickoff
    for every active autoresearch pipeline.

    Triggered once per day by a Temporal schedule. For each pipeline whose status
    is RUNNING or CONVERGED and whose cadence_days have elapsed since last_scored_at
    it starts:
      - AutoresearchInferenceWorkflow  — scores users, emits prediction events
      - AutoresearchValidationWorkflow — validates predictions from horizon days ago
      - activity_kickoff_training      — starts a new agent training run if eligible

    All three steps run concurrently. Per-pipeline failures — raised exceptions and
    activity results that report a soft failure — are logged and counted in
    pipelines_errored, but do not prevent other pipelines from running.
    """

    inputs_cls = CoordinatorWorkflowInput

    @workflow.run
    async def run(self, inp: CoordinatorWorkflowInput) -> CoordinatorWorkflowResult:
        run_date = inp.run_date or workflow.now().strftime("%Y-%m-%d")

        workflow.logger.info("autoresearch_coordinator_start", run_date=run_date)

        active = await workflow.execute_activity(
            activity_load_active_pipelines,
            LoadActivePipelinesInput(),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=_COORDINATOR_RETRY,
        )

        if not active.due:
            workflow.logger.info("autoresearch_coordinator_no_active_pipelines")
            return CoordinatorWorkflowResult(pipelines_processed=0, pipelines_errored=0, status="completed")

        outcomes = await _asyncio.gather(
            *[self._run_pipeline(due, run_date) for due in active.due],
            return_exceptions=True,
        )

        errored = sum(1 for o in outcomes if isinstance(o, BaseException) or not o.succeeded)
        processed = len(outcomes) - errored

        workflow.logger.info(
            "autoresearch_coordinator_complete",
            run_date=run_date,
            pipelines_processed=processed,
            pipelines_errored=errored,
        )

        return CoordinatorWorkflowResult(
            pipelines_processed=processed,
            pipelines_errored=errored,
            status="completed" if errored == 0 else "partial",
        )

    async def _run_pipeline(self, due: DuePipeline, run_date: str) -> PipelineRunOutcome:
        """Run inference, validation, and training kickoff for one pipeline."""
        pipeline_id = due.pipeline_id
        inference_result, validation_result, kickoff_result = await _asyncio.gather(
            workflow.execute_child_workflow(
                AutoresearchInferenceWorkflow.run,
                InferenceWorkflowInput(pipeline_id=pipeline_id, team_id=due.team_id, prediction_date=run_date),
                id=f"autoresearch-inference-{pipeline_id}-{run_date}",
                execution_timeout=timedelta(hours=3),
            ),
            workflow.execute_child_workflow(
                AutoresearchValidationWorkflow.run,
                ValidationWorkflowInput(pipeline_id=pipeline_id, team_id=due.team_id),
                id=f"autoresearch-validation-{pipeline_id}-{run_date}",
                execution_timeout=timedelta(hours=2),
            ),
            workflow.execute_activity(
                activity_kickoff_training,
                KickoffTrainingInput(pipeline_id=pipeline_id, team_id=due.team_id),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_KICKOFF_RETRY,
            ),
            return_exceptions=True,
        )
        outcome = evaluate_pipeline_outcome(
            pipeline_id=pipeline_id,
            inference=inference_result,
            validation=validation_result,
            kickoff=kickoff_result,
        )
        for error in outcome.errors:
            workflow.logger.warning(
                "autoresearch_pipeline_step_failed",
                pipeline_id=pipeline_id,
                error=error,
            )
        return outcome
