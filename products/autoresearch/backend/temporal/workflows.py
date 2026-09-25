"""
Temporal workflows for autoresearch inference and online validation.

Both workflows are regular Temporal workflows (not TaskRun/agent sandboxes) because
scoring and validation are deterministic pipelines. Training runs through Task/TaskRun.

Activities are synchronous — Temporal runs them in a thread pool, which is correct
for Django ORM + HogQL queries. Workflows are async and only orchestrate activities.
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import field
from datetime import date, timedelta
from typing import TYPE_CHECKING, Optional, TypeVar

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    import asyncio as _asyncio

    from django.db import transaction
    from django.utils import timezone as django_timezone

    from products.actions.backend.models.action import Action
    from products.autoresearch.backend.access import has_autoresearch_access
    from products.autoresearch.backend.evaluation.online_validation import run_online_validation_for_pipeline
    from products.autoresearch.backend.inference.sandbox import SandboxInferenceError, _resolve_acting_user
    from products.autoresearch.backend.inference.scoring import run_inference_for_pipeline
    from products.autoresearch.backend.models import (
        AutoresearchModel,
        AutoresearchPipeline,
        AutoresearchRun,
        AutoresearchTrainingRun,
    )
    from products.autoresearch.backend.training.runner import run_training
    from products.tasks.backend.facade.access import get_desktop_access_decision
    from products.tasks.backend.facade.usage import task_run_usage_limited

from posthog.dataclasses import frozen
from posthog.models.scoping import team_scope
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync

if TYPE_CHECKING:
    from posthog.models import Organization, User

logger = structlog.get_logger(__name__)

_T = TypeVar("_T")

# The statuses the daily sweep scores and validates. Each activity re-reads the status, so a
# pipeline paused after the sweep loaded it is not scored.
_LIVE_STATUSES = (AutoresearchPipeline.Status.RUNNING, AutoresearchPipeline.Status.CONVERGED)


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
class RunInferenceInput:
    pipeline_id: str
    team_id: int
    prediction_date: str  # ISO date string


@frozen
class RunInferenceResult:
    run_id: str
    rows_scored: int
    status: str
    error: Optional[str] = None


# ── Activities ───────────────────────────────────────────────────────────────


@activity.defn(name="autoresearch-inference.run_inference")
def activity_run_inference(inp: RunInferenceInput) -> RunInferenceResult:
    """Score the inference population with the current champion and emit autoresearch_prediction events.

    The champion is read here, not passed in, so a retry after a promotion during scoring scores
    with the new champion instead of failing again on the archived one.
    """
    with HeartbeaterSync(), team_scope(inp.team_id):
        pipeline = AutoresearchPipeline.objects.select_related("team").get(pk=inp.pipeline_id)
        if pipeline.status not in _LIVE_STATUSES:
            return RunInferenceResult(run_id="", rows_scored=0, status="skipped")
        model = (
            AutoresearchModel.objects.filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
            .order_by("-created_at")
            .first()
        )
        if model is None:
            raise ApplicationError(f"No champion model for pipeline {inp.pipeline_id}", non_retryable=True)
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

# Scoring can take minutes for large populations.
_SCORE_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=30))
_SCORE_ATTEMPT_TIMEOUT = timedelta(hours=2)
# A lost worker is detected in minutes rather than at the end of a multi-hour attempt.
_HEARTBEAT_TIMEOUT = timedelta(minutes=2)
# Covers both attempts plus their backoff, so the child never cuts off a retry.
_INFERENCE_WORKFLOW_TIMEOUT = timedelta(hours=5)


@workflow.defn(name="autoresearch-inference")
class AutoresearchInferenceWorkflow(PostHogWorkflow):
    """
    Temporal workflow that runs daily inference for one autoresearch pipeline.

    One activity scores the inference population with the current champion and emits
    autoresearch_prediction events. It delegates to products.autoresearch.backend.inference.scoring so the same
    code is exercised by both the Temporal workflow and the local management
    command (autoresearch_score).
    """

    inputs_cls = InferenceWorkflowInput

    @workflow.run
    async def run(self, inp: InferenceWorkflowInput) -> InferenceWorkflowResult:
        workflow.logger.info(
            "autoresearch_inference_workflow_start",
            extra={"pipeline_id": inp.pipeline_id, "prediction_date": inp.prediction_date},
        )

        result = await workflow.execute_activity(
            activity_run_inference,
            RunInferenceInput(
                pipeline_id=inp.pipeline_id,
                team_id=inp.team_id,
                prediction_date=inp.prediction_date,
            ),
            start_to_close_timeout=_SCORE_ATTEMPT_TIMEOUT,
            heartbeat_timeout=_HEARTBEAT_TIMEOUT,
            retry_policy=_SCORE_RETRY,
        )

        workflow.logger.info(
            "autoresearch_inference_workflow_complete",
            extra={
                "pipeline_id": inp.pipeline_id,
                "run_id": result.run_id,
                "rows_scored": result.rows_scored,
                "status": result.status,
            },
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
_VALIDATION_ATTEMPT_TIMEOUT = timedelta(hours=1)
_VALIDATION_WORKFLOW_TIMEOUT = timedelta(hours=3)


@activity.defn(name="autoresearch-validation.run_validation")
def activity_run_validation(inp: RunValidationInput) -> RunValidationResult:
    """Find all matured unvalidated prediction dates and validate each one."""
    with HeartbeaterSync(), team_scope(inp.team_id):
        pipeline = AutoresearchPipeline.objects.select_related("team").get(pk=inp.pipeline_id)
        if pipeline.status not in _LIVE_STATUSES:
            return RunValidationResult(dates_validated=0, total_rows=0, status="skipped")
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
        workflow.logger.info("autoresearch_validation_workflow_start", extra={"pipeline_id": inp.pipeline_id})

        result = await workflow.execute_activity(
            activity_run_validation,
            RunValidationInput(pipeline_id=inp.pipeline_id, team_id=inp.team_id),
            start_to_close_timeout=_VALIDATION_ATTEMPT_TIMEOUT,
            heartbeat_timeout=_HEARTBEAT_TIMEOUT,
            retry_policy=_VALIDATION_RETRY,
        )

        workflow.logger.info(
            "autoresearch_validation_workflow_complete",
            extra={
                "pipeline_id": inp.pipeline_id,
                "dates_validated": result.dates_validated,
                "total_rows": result.total_rows,
                "status": result.status,
            },
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
class ActivePipeline:
    pipeline_id: str
    team_id: int
    # Validation runs on every sweep; scoring and training kickoff only on a cadence day.
    score_due: bool


@frozen
class LoadActivePipelinesResult:
    pipelines: list[ActivePipeline]


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
    inference: InferenceWorkflowResult | BaseException | None,
    validation: ValidationWorkflowResult | BaseException,
    kickoff: KickoffTrainingResult | BaseException | None,
) -> PipelineRunOutcome:
    """Classify one pipeline's step results, treating soft-failed activity results as failures too.

    ``None`` is a step the sweep did not start, because the pipeline was not due for scoring.
    """
    errors: list[str] = []

    if inference is None:
        pass
    elif isinstance(inference, BaseException):
        errors.append(f"inference: {inference}")
    elif inference.status == "failed":
        errors.append(f"inference: {inference.error or 'failed'}")

    if isinstance(validation, BaseException):
        errors.append(f"validation: {validation}")
    elif validation.status == "failed":
        errors.append(f"validation: {validation.error or 'failed'}")

    if kickoff is None:
        pass
    elif isinstance(kickoff, BaseException):
        errors.append(f"training kickoff: {kickoff}")
    elif kickoff.error:
        errors.append(f"training kickoff ({kickoff.reason}): {kickoff.error}")

    return PipelineRunOutcome(pipeline_id=pipeline_id, succeeded=not errors, errors=errors)


@frozen
class KickoffTrainingResult:
    kicked_off: bool
    # "started" | "budget_exhausted" | "already_running" | "already_ran_today" | "not_eligible"
    # | "tasks_gated" | "no_creator" | "not_launchable"
    reason: str
    error: Optional[str] = None
    # Why an expected skip happened, without counting it as a failure.
    detail: Optional[str] = None


# ── Coordinator activities ────────────────────────────────────────────────────

_COORDINATOR_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5))
_KICKOFF_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=10))


@activity.defn(name="autoresearch-coordinator.load_active_pipelines")
def activity_load_active_pipelines(inp: LoadActivePipelinesInput) -> LoadActivePipelinesResult:
    """Return every live pipeline the sweep runs, across every team, and whether each is due for scoring.

    A pipeline whose creator no longer has access to its team is paused here, before any run is
    dispatched, because every scheduled query and training run acts as the creator. A pipeline
    outside the ``autoresearch`` rollout is skipped but stays live, so it resumes when the rollout
    reaches it again.
    """
    today = django_timezone.now().date()
    # unscoped() because the coordinator's job is exactly to sweep every team. The
    # pipelines it returns carry their team so the downstream activities can scope.
    candidates = (
        AutoresearchPipeline.objects.unscoped()
        .filter(status__in=_LIVE_STATUSES)
        .select_related("team", "created_by")
        .order_by("created_at")
    )
    pipelines: list[ActivePipeline] = []
    for pipeline in candidates:
        try:
            creator = _resolve_acting_user(team=pipeline.team, pipeline=pipeline, user=None)
        except SandboxInferenceError as exc:
            _pause_orphaned_pipeline(pipeline, reason=str(exc))
            continue
        if not has_autoresearch_access(
            creator, team_id=pipeline.team_id, organization_id=str(pipeline.team.organization_id)
        ):
            continue
        # By calendar day, because a run finishes some time after the 02:00 UTC tick and an
        # elapsed-time comparison would skip the next day's tick.
        last_scored = pipeline.last_scored_at.date() if pipeline.last_scored_at else None
        pipelines.append(
            ActivePipeline(
                pipeline_id=str(pipeline.pk),
                team_id=pipeline.team_id,
                score_due=last_scored is None or (today - last_scored).days >= pipeline.cadence_days,
            )
        )
    return LoadActivePipelinesResult(pipelines=pipelines)


def _pause_orphaned_pipeline(pipeline: AutoresearchPipeline, *, reason: str) -> None:
    # Conditional on the status read above, so a concurrent archive or pause keeps its outcome.
    paused = (
        AutoresearchPipeline.objects.unscoped()
        .filter(pk=pipeline.pk, status=pipeline.status)
        .update(status=AutoresearchPipeline.Status.PAUSED, updated_at=django_timezone.now())
    )
    if paused:
        logger.warning("autoresearch_pipeline_paused_creator_lost_access", pipeline_id=str(pipeline.pk), reason=reason)


@activity.defn(name="autoresearch-coordinator.kickoff_training")
def activity_kickoff_training(inp: KickoffTrainingInput) -> KickoffTrainingResult:
    """Spend part of the iteration budget on a new agent training run, if the pipeline is eligible.

    The deduction, the run row, and its task binding commit together under the pipeline row lock,
    as in the facade's ``start_training``. A manual start cannot interleave, and a failed launch
    rolls the deduction back. A launch failure raises, so the activity retry applies.
    """
    # The gates can call out to billing and flags, so they run before the row lock is taken.
    with team_scope(inp.team_id):
        loaded = AutoresearchPipeline.objects.select_related("created_by", "team__organization").get(pk=inp.pipeline_id)
    if loaded.created_by is not None and (
        gate := _tasks_gate(loaded.created_by, loaded.team.organization, inp.team_id)
    ):
        return KickoffTrainingResult(kicked_off=False, reason="tasks_gated", detail=gate)

    with team_scope(inp.team_id), transaction.atomic():
        pipeline = AutoresearchPipeline.objects.select_for_update().get(pk=inp.pipeline_id)

        if pipeline.status != AutoresearchPipeline.Status.RUNNING:
            return KickoffTrainingResult(kicked_off=False, reason="not_eligible")

        # The column is nullable (an admin can clear it); read that as exhausted rather
        # than refunding the budget mid-flight.
        remaining = pipeline.iteration_budget_remaining
        if remaining is None or remaining <= 0:
            return KickoffTrainingResult(kicked_off=False, reason="budget_exhausted")

        if AutoresearchTrainingRun.objects.filter(
            pipeline=pipeline,
            status__in=[AutoresearchTrainingRun.Status.PENDING, AutoresearchTrainingRun.Status.RUNNING],
        ).exists():
            return KickoffTrainingResult(kicked_off=False, reason="already_running")

        # At most one scheduled run per UTC day. A retry after a lost activity response must not
        # launch a second paid run once the first has already ended.
        today = django_timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if AutoresearchTrainingRun.objects.filter(pipeline=pipeline, created_at__gte=today).exists():
            return KickoffTrainingResult(kicked_off=False, reason="already_ran_today")

        # Training runs in a Tasks sandbox that requires a real owning user. CLI-created
        # pipelines have no creator, so fail before spending budget rather than launching
        # a run that would crash in the tasks facade.
        if pipeline.created_by_id is None:
            error = f"Pipeline {inp.pipeline_id} has no creator; training kickoff requires created_by to own the task"
            logger.error(
                "autoresearch_kickoff_training_no_creator",
                pipeline_id=inp.pipeline_id,
            )
            return KickoffTrainingResult(kicked_off=False, reason="no_creator", error=error)

        daily_budget = min(10, remaining)
        try:
            with transaction.atomic():
                pipeline.iteration_budget_remaining = remaining - daily_budget
                pipeline.save(update_fields=["iteration_budget_remaining"])
                run_training(pipeline=pipeline, iteration_budget=daily_budget, user_id=pipeline.created_by_id)
        except (ValueError, SandboxInferenceError, Action.DoesNotExist) as exc:
            # run_training refuses a departed creator or an unresolvable target before it writes
            # anything. A retry cannot fix either, so these report instead of raising.
            return KickoffTrainingResult(kicked_off=False, reason="not_launchable", error=str(exc))
    return KickoffTrainingResult(kicked_off=True, reason="started")


def _tasks_gate(creator: User, organization: Organization, team_id: int) -> str | None:
    """Why the creator may not launch a paid Tasks sandbox now, or None. Mirrors the `/train` gates.

    An unresolvable Desktop access decision raises, so the activity retries instead of launching.
    """
    decision = get_desktop_access_decision(creator, organization)
    if not decision.allowed:
        return f"PostHog Desktop access: {decision.value}"
    if task_run_usage_limited(creator, team_id):
        return "The Tasks usage limit is reached"
    return None


# ── Coordinator workflow ──────────────────────────────────────────────────────


@workflow.defn(name="autoresearch-coordinator")
class AutoresearchCoordinatorWorkflow(PostHogWorkflow):
    """
    Daily coordinator that fans out inference, validation, and training kickoff
    for every active autoresearch pipeline.

    Triggered once per day by a Temporal schedule. For each pipeline whose status
    is RUNNING or CONVERGED it starts AutoresearchValidationWorkflow, which validates every
    matured prediction date. When the pipeline's cadence_days have elapsed since the calendar
    day of last_scored_at it also starts:
      - AutoresearchInferenceWorkflow  — scores users, emits prediction events
      - activity_kickoff_training      — starts a new agent training run if eligible, once
        inference ends, so a champion promoted mid-scoring cannot fail the scoring run

    Per-pipeline failures — raised exceptions and
    activity results that report a soft failure — are logged and counted in
    pipelines_errored, but do not prevent other pipelines from running.
    """

    inputs_cls = CoordinatorWorkflowInput

    @workflow.run
    async def run(self, inp: CoordinatorWorkflowInput) -> CoordinatorWorkflowResult:
        run_date = inp.run_date or workflow.now().strftime("%Y-%m-%d")

        workflow.logger.info("autoresearch_coordinator_start", extra={"run_date": run_date})

        active = await workflow.execute_activity(
            activity_load_active_pipelines,
            LoadActivePipelinesInput(),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=_COORDINATOR_RETRY,
        )

        if not active.pipelines:
            workflow.logger.info("autoresearch_coordinator_no_active_pipelines")
            return CoordinatorWorkflowResult(pipelines_processed=0, pipelines_errored=0, status="completed")

        outcomes = await _asyncio.gather(
            *[self._run_pipeline(pipeline, run_date) for pipeline in active.pipelines],
            return_exceptions=True,
        )

        errored = sum(1 for o in outcomes if isinstance(o, BaseException) or not o.succeeded)
        processed = len(outcomes) - errored

        workflow.logger.info(
            "autoresearch_coordinator_complete",
            extra={"run_date": run_date, "pipelines_processed": processed, "pipelines_errored": errored},
        )

        return CoordinatorWorkflowResult(
            pipelines_processed=processed,
            pipelines_errored=errored,
            status="completed" if errored == 0 else "partial",
        )

    async def _run_pipeline(self, pipeline: ActivePipeline, run_date: str) -> PipelineRunOutcome:
        """Run validation, and on a cadence day inference then training kickoff, for one pipeline."""
        pipeline_id = pipeline.pipeline_id
        validation = _settle(
            workflow.execute_child_workflow(
                AutoresearchValidationWorkflow.run,
                ValidationWorkflowInput(pipeline_id=pipeline_id, team_id=pipeline.team_id),
                id=f"autoresearch-validation-{pipeline_id}-{run_date}",
                execution_timeout=_VALIDATION_WORKFLOW_TIMEOUT,
            )
        )
        inference_result: InferenceWorkflowResult | BaseException | None = None
        kickoff_result: KickoffTrainingResult | BaseException | None = None
        if pipeline.score_due:
            validation_result, inference_result = await _asyncio.gather(
                validation,
                _settle(
                    workflow.execute_child_workflow(
                        AutoresearchInferenceWorkflow.run,
                        InferenceWorkflowInput(
                            pipeline_id=pipeline_id, team_id=pipeline.team_id, prediction_date=run_date
                        ),
                        id=f"autoresearch-inference-{pipeline_id}-{run_date}",
                        execution_timeout=_INFERENCE_WORKFLOW_TIMEOUT,
                    )
                ),
            )
            kickoff_result = await _settle(
                workflow.execute_activity(
                    activity_kickoff_training,
                    KickoffTrainingInput(pipeline_id=pipeline_id, team_id=pipeline.team_id),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=_KICKOFF_RETRY,
                )
            )
        else:
            validation_result = await validation
        outcome = evaluate_pipeline_outcome(
            pipeline_id=pipeline_id,
            inference=inference_result,
            validation=validation_result,
            kickoff=kickoff_result,
        )
        for error in outcome.errors:
            workflow.logger.warning(
                "autoresearch_pipeline_step_failed",
                extra={"pipeline_id": pipeline_id, "error": error},
            )
        return outcome


async def _settle(awaitable: Awaitable[_T]) -> _T | BaseException:
    """Return a step's exception instead of raising it, so one failed step does not end the others."""
    try:
        return await awaitable
    except Exception as exc:
        return exc
