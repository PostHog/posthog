"""
Temporal workflows for autoresearch inference, online validation, and person property cleanup.

These workflows are regular Temporal workflows (not TaskRun/agent sandboxes) because
scoring and validation are deterministic pipelines. Training runs through Task/TaskRun.

Activities are synchronous — Temporal runs them in a thread pool, which is correct
for Django ORM + HogQL queries. Workflows are async and only orchestrate activities.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import field, replace
from datetime import date, timedelta
from functools import partial
from typing import Optional, TypeVar, cast

from django.core.cache import cache

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, ApplicationError, ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    import asyncio as _asyncio

    from django.db import transaction
    from django.db.models import QuerySet
    from django.utils import timezone as django_timezone

    from posthog.models.team.team import Team
    from posthog.models.user import User

    from products.actions.backend.models.action import Action
    from products.autoresearch.backend.access import has_autoresearch_access
    from products.autoresearch.backend.dataset.labeling import build_target_condition
    from products.autoresearch.backend.evaluation.online_validation import run_online_validation_for_pipeline
    from products.autoresearch.backend.inference.failures import (
        INFERENCE_WORKFLOW_TIMEOUT,
        UNSCORABLE_AFTER_FAILED_DAYS,
        fail_lost_scheduled_runs,
        fail_stale_inference_runs,
        find_unscorable_champion,
        scheduled_run_can_retry,
    )
    from products.autoresearch.backend.inference.person_property import remove_output_person_property
    from products.autoresearch.backend.inference.sandbox import SandboxInferenceError, _resolve_acting_user
    from products.autoresearch.backend.inference.scoring import (
        discard_scored_persons,
        discard_scored_persons_for,
        run_inference_for_pipeline,
        score_shadow_set_for_run,
    )
    from products.autoresearch.backend.models import (
        AutoresearchModel,
        AutoresearchPipeline,
        AutoresearchRun,
        AutoresearchTrainingRun,
    )
    from products.autoresearch.backend.query import BATCH_QUERY, SCORING_QUERY
    from products.autoresearch.backend.training.runner import run_training
    from products.autoresearch.backend.training.schedule import research_schedule, schedule_runs_for
    from products.tasks.backend.facade.access import get_desktop_access_decision
    from products.tasks.backend.facade.usage import task_run_usage_limited

from posthog.dataclasses import frozen
from posthog.models.scoping import team_scope
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync

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
    # Set by a manual "Score now": the run row the API already returned, and the user who asked.
    run_id: Optional[str] = None
    user_id: Optional[int] = None
    # Set by the daily sweep, which scores the shadow set in its own activity after every champion.
    defer_shadows: bool = False
    # The sweep's bound on pipelines in flight, recorded on the run.
    coordinator_concurrency: Optional[int] = None


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
    run_id: Optional[str] = None
    user_id: Optional[int] = None
    defer_shadows: bool = False
    coordinator_concurrency: Optional[int] = None


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

    A manual run (``run_id`` set) fills the row the API created, and a refusal fails that row,
    so the caller that polls it sees the outcome. A retry of a scheduled run fills the row the
    first attempt created, so a lost attempt does not leave a second row for the same date.
    """
    with HeartbeaterSync(), team_scope(inp.team_id):
        pipeline = AutoresearchPipeline.objects.select_related("team__organization", "created_by").get(
            pk=inp.pipeline_id
        )
        manual_run = AutoresearchRun.objects.filter(pk=inp.run_id, pipeline=pipeline).first() if inp.run_id else None
        if inp.run_id and manual_run is None:
            raise ApplicationError(f"Inference run {inp.run_id} does not exist", non_retryable=True)
        if manual_run is not None:
            # The API already applied the manual gates, so only a pause or archive since then stops it.
            if pipeline.status in (AutoresearchPipeline.Status.PAUSED, AutoresearchPipeline.Status.ARCHIVED):
                _fail_run(manual_run, "The pipeline was paused or archived before scoring started.")
                return RunInferenceResult(run_id=str(manual_run.pk), rows_scored=0, status="skipped")
        elif pipeline.status not in _LIVE_STATUSES or _sweep_access_block(pipeline):
            return RunInferenceResult(run_id="", rows_scored=0, status="skipped")
        try:
            user = _manual_run_user(inp.user_id)
            model = _champion_for_inference(pipeline)
        except ApplicationError as exc:
            if manual_run is not None:
                _fail_run(manual_run, str(exc))
            raise
        run = run_inference_for_pipeline(
            pipeline=pipeline,
            model=model,
            prediction_date=date.fromisoformat(inp.prediction_date),
            user=user,
            run=manual_run or _open_scheduled_run(pipeline, inp.prediction_date),
            query_context=SCORING_QUERY,
            scheduled=manual_run is None,
            defer_shadows=inp.defer_shadows,
            extra_metrics=_scheduled_run_metrics(inp) if manual_run is None else None,
        )
    return RunInferenceResult(
        run_id=str(run.pk),
        rows_scored=run.rows_scored or 0,
        status=run.status,
        error=run.error or None,
    )


def _scheduled_run_metrics(inp: RunInferenceInput) -> dict[str, object]:
    # The workflow run id lets the coordinator close only the rows of the child execution that failed.
    metrics: dict[str, object] = {"workflow_run_id": activity.info().workflow_run_id}
    if inp.coordinator_concurrency is not None:
        metrics["coordinator_concurrency"] = inp.coordinator_concurrency
    return metrics


def _open_scheduled_run(pipeline: AutoresearchPipeline, prediction_date: str) -> AutoresearchRun | None:
    """The RUNNING row an earlier attempt of this scheduled run created, or None on the first attempt."""
    return (
        AutoresearchRun.objects.filter(
            pipeline=pipeline,
            run_type=AutoresearchRun.RunType.INFERENCE,
            scheduled=True,
            status=AutoresearchRun.Status.RUNNING,
            started_at__gte=django_timezone.now() - INFERENCE_WORKFLOW_TIMEOUT,
            metrics__prediction_date=prediction_date,
        )
        .order_by("-started_at")
        .first()
    )


def _champion_for_inference(pipeline: AutoresearchPipeline) -> AutoresearchModel:
    try:
        # A bundle champion never resolves the target, so a deleted or stepless action would
        # otherwise score and advance last_scored_at. Manual scoring refuses it the same way.
        build_target_condition(
            target_event=pipeline.target_event, target_definition=pipeline.target_definition, team=pipeline.team
        )
    except (ValueError, Action.DoesNotExist) as exc:
        raise ApplicationError(f"The pipeline's target cannot be resolved: {exc}", non_retryable=True)
    model = (
        AutoresearchModel.objects.filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
        .order_by("-created_at")
        .first()
    )
    if model is None:
        raise ApplicationError(f"No champion model for pipeline {pipeline.pk}", non_retryable=True)
    return model


def _manual_run_user(user_id: int | None) -> User | None:
    """The user who asked for a manual run, so HogQL applies their access and not the creator's."""
    if user_id is None:
        return None
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        raise ApplicationError("The user who started this run no longer exists", non_retryable=True)
    return user


def _fail_run(run: AutoresearchRun, error: str) -> None:
    run.status = AutoresearchRun.Status.FAILED
    run.error = error[:2000]
    run.completed_at = django_timezone.now()
    run.save(update_fields=["status", "error", "completed_at"])


def inference_workflow_id(pipeline_id: str, prediction_date: str) -> str:
    """One inference workflow per pipeline and date, shared by the daily sweep and manual scoring."""
    return f"autoresearch-inference-{pipeline_id}-{prediction_date}"


# ── Workflow ─────────────────────────────────────────────────────────────────

# Scoring can take minutes for large populations. The recipe path runs at most five batch
# queries in sequence (50 minutes at the full limit). Shadow scoring then starts models for up to
# SHADOW_TIME_BUDGET_S (20 minutes), and the last model it starts runs an anchor count, a feature
# query, and a predict sandbox (about 30 minutes at worst). One attempt covers all of it.
_SCORE_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=30))
_SCORE_ATTEMPT_TIMEOUT = timedelta(hours=2)
# A lost worker is detected in minutes rather than at the end of a multi-hour attempt.
_HEARTBEAT_TIMEOUT = timedelta(minutes=2)
# INFERENCE_WORKFLOW_TIMEOUT covers both attempts plus their backoff, so the child never cuts off a retry.


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
                run_id=inp.run_id,
                user_id=inp.user_id,
                defer_shadows=inp.defer_shadows,
                coordinator_concurrency=inp.coordinator_concurrency,
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


# ── Shadow scoring ────────────────────────────────────────────────────────────


@frozen
class RunShadowScoringInput:
    pipeline_id: str
    team_id: int
    # The champion's completed run. The activity reads the people it scored from the row.
    run_id: str


@frozen
class RunShadowScoringResult:
    completed: int
    failed: int
    skipped: int
    status: str


# SHADOW_TIME_BUDGET_S (20 minutes), plus the last model it starts: an anchor count, a feature query,
# and a predict sandbox (about 30 minutes at worst).
_SHADOW_ATTEMPT_TIMEOUT = timedelta(hours=1)
# One attempt, because a retry would open a second shadow run for each model it already scored.
_SHADOW_RETRY = RetryPolicy(maximum_attempts=1)


@activity.defn(name="autoresearch-coordinator.run_shadow_scoring")
def activity_run_shadow_scoring(inp: RunShadowScoringInput) -> RunShadowScoringResult:
    """Score the shadow set against the people a champion's completed run scored.

    The daily sweep starts this after every champion has scored. It writes only shadow runs and the
    champion run's ``shadow_models``, so a failure here never fails the champion's run.
    """
    with HeartbeaterSync(), team_scope(inp.team_id):
        run = (
            AutoresearchRun.objects.select_related("pipeline__team__organization", "pipeline__created_by", "model")
            .filter(pk=inp.run_id, pipeline__pk=inp.pipeline_id, run_type=AutoresearchRun.RunType.INFERENCE)
            .first()
        )
        if run is None:
            # A deleted pipeline cascades to its runs, so the key comes from the input to clean up the stored people.
            discard_scored_persons_for(team_id=inp.team_id, pipeline_id=inp.pipeline_id, inference_run_id=inp.run_id)
            return RunShadowScoringResult(completed=0, failed=0, skipped=0, status="skipped")
        if run.pipeline.status not in _LIVE_STATUSES or _sweep_access_block(run.pipeline):
            discard_scored_persons(run)
            return RunShadowScoringResult(completed=0, failed=0, skipped=0, status="skipped")
        outcome = score_shadow_set_for_run(run, query_context=SCORING_QUERY)
    if outcome is None:
        return RunShadowScoringResult(completed=0, failed=0, skipped=0, status="skipped")
    return RunShadowScoringResult(
        completed=len(outcome.completed),
        failed=len(outcome.failed),
        skipped=len(outcome.skipped),
        status="completed",
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
# Each date runs one predictions query per model that scored it, up to the five models of a
# shadow set, plus one realized-labels query. Each takes up to HOGQL_INCREASED_MAX_EXECUTION_TIME
# (600 s). An attempt claims another date only while that worst case, plus the metrics and
# writes, still fits in the attempt. The rest of a larger backlog stays pending for the next
# sweep, so the attempt completes instead of timing out part-way.
_VALIDATION_ATTEMPT_TIMEOUT = timedelta(hours=2)
_VALIDATION_DATE_RESERVE = timedelta(minutes=70)
# Covers both attempts plus their backoff, as for inference. Online validation treats a RUNNING
# row older than INFERENCE_WORKFLOW_TIMEOUT as dead, so keep this no longer than that.
_VALIDATION_WORKFLOW_TIMEOUT = timedelta(hours=5)


@activity.defn(name="autoresearch-validation.run_validation")
def activity_run_validation(inp: RunValidationInput) -> RunValidationResult:
    """Find all matured unvalidated prediction dates and validate each one."""
    claim_deadline = django_timezone.now() + _VALIDATION_ATTEMPT_TIMEOUT - _VALIDATION_DATE_RESERVE
    with HeartbeaterSync(), team_scope(inp.team_id):
        pipeline = AutoresearchPipeline.objects.select_related("team__organization", "created_by").get(
            pk=inp.pipeline_id
        )
        if pipeline.status not in _LIVE_STATUSES or _sweep_access_block(pipeline):
            return RunValidationResult(dates_validated=0, total_rows=0, status="skipped")
        runs = run_online_validation_for_pipeline(pipeline, query_context=BATCH_QUERY, claim_deadline=claim_deadline)
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


# ── Person property cleanup ───────────────────────────────────────────────────


@frozen
class PropertyCleanupWorkflowInput:
    pipeline_id: str
    team_id: int
    # Carried in the input, because a deleted pipeline has no row to read them from.
    output_property: str
    # The pipeline's creation time, so the scan for its prediction events stays bounded.
    written_since: Optional[str] = None
    # The AutoresearchRun row the cleanup fills. None for a deleted pipeline.
    run_id: Optional[str] = None
    # Who turned the setting off, archived, or deleted, so HogQL applies their access.
    user_id: Optional[int] = None
    # The first pass leaves the run open, so the run completes only after the reconcile pass.
    final_pass: bool = True


@frozen
class PropertyCleanupWorkflowResult:
    persons_cleared: int
    status: str
    stopped: Optional[str] = None


# A page reads at most CLEANUP_PAGE_SIZE persons and sends one capture batch, so one attempt covers
# a large population. The cleanup restarts from the first person that still holds the property.
_CLEANUP_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(minutes=1))
_CLEANUP_ATTEMPT_TIMEOUT = timedelta(hours=2)
# A scoring batch capture accepted just before the opt-out can still be ingesting when the first pass
# runs, and its $set lands after it. A second pass after this delay removes those.
_RECONCILE_DELAY = timedelta(hours=1)
# Two passes of up to three attempts each, plus the delay between them and the retry backoff.
PROPERTY_CLEANUP_WORKFLOW_TIMEOUT = timedelta(hours=16)


@activity.defn(name="autoresearch-property-cleanup.remove_person_property")
def activity_remove_person_property(inp: PropertyCleanupWorkflowInput) -> PropertyCleanupWorkflowResult:
    """Send $unset for the pipeline's output property to the persons it wrote it to.

    The run row is updated through the queryset, because deleting the pipeline also deletes its runs.
    The count continues from the row, so a retry or the reconcile pass adds to what earlier attempts
    cleared. A failed attempt leaves the run open, and the workflow fails it once retries run out.
    """
    with HeartbeaterSync(), team_scope(inp.team_id):
        _update_cleanup_run(inp.run_id, status=AutoresearchRun.Status.RUNNING, error="", completed_at=None)
        cleared_before = _cleanup_run_count(inp.run_id)
        team = Team.objects.get(pk=inp.team_id)
        user = User.objects.filter(pk=inp.user_id, is_active=True).first() if inp.user_id else None
        outcome = remove_output_person_property(
            team=team,
            pipeline_id=inp.pipeline_id,
            output_property=inp.output_property,
            written_since=inp.written_since,
            user=user,
            query_context=BATCH_QUERY,
            on_page=lambda cleared: _update_cleanup_run(inp.run_id, rows_scored=cleared_before + cleared),
        )
        cleared = cleared_before + outcome.persons_cleared
        done = inp.final_pass or outcome.stopped is not None
        status = AutoresearchRun.Status.COMPLETED if done else AutoresearchRun.Status.RUNNING
        _update_cleanup_run(
            inp.run_id,
            status=status,
            rows_scored=cleared,
            metrics={"output_person_property": inp.output_property, "stopped": outcome.stopped},
            completed_at=django_timezone.now() if done else None,
        )
    return PropertyCleanupWorkflowResult(persons_cleared=cleared, status=status, stopped=outcome.stopped)


@frozen
class FailCleanupRunInput:
    run_id: str
    error: str


@activity.defn(name="autoresearch-property-cleanup.fail_run")
def activity_fail_cleanup_run(inp: FailCleanupRunInput) -> None:
    """Fail the run after the cleanup ran out of retries, timed out, or lost its worker."""
    _update_cleanup_run(
        inp.run_id, status=AutoresearchRun.Status.FAILED, error=inp.error[:2000], completed_at=django_timezone.now()
    )


def _cleanup_runs(run_id: str) -> QuerySet[AutoresearchRun]:
    return AutoresearchRun.objects.filter(pk=run_id, run_type=AutoresearchRun.RunType.PROPERTY_CLEANUP)


def _update_cleanup_run(run_id: str | None, **fields: object) -> None:
    if run_id is not None:
        _cleanup_runs(run_id).update(**fields)


def _cleanup_run_count(run_id: str | None) -> int:
    if run_id is None:
        return 0
    return _cleanup_runs(run_id).values_list("rows_scored", flat=True).first() or 0


def property_cleanup_workflow_id(pipeline_id: str, request_id: str) -> str:
    """One workflow per cleanup request, so a request never waits on, or is lost to, an earlier one that is stopping."""
    return f"autoresearch-property-cleanup-{pipeline_id}-{request_id}"


@workflow.defn(name="autoresearch-property-cleanup")
class AutoresearchPropertyCleanupWorkflow(PostHogWorkflow):
    """
    Removes a pipeline's output person property from persons, after someone turns off
    write_person_property, or archives or deletes a pipeline that had it on. A reconcile pass
    runs after _RECONCILE_DELAY for scores that were still ingesting during the first pass.
    """

    inputs_cls = PropertyCleanupWorkflowInput

    @workflow.run
    async def run(self, inp: PropertyCleanupWorkflowInput) -> PropertyCleanupWorkflowResult:
        try:
            first = await self._remove(replace(inp, final_pass=False))
            if first.stopped is not None:
                return first
            await workflow.sleep(_RECONCILE_DELAY)
            return await self._remove(replace(inp, final_pass=True))
        except ActivityError as exc:
            if inp.run_id is not None:
                await workflow.execute_activity(
                    activity_fail_cleanup_run,
                    FailCleanupRunInput(run_id=inp.run_id, error=str(exc.cause or exc)),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=5),
                )
            raise

    async def _remove(self, inp: PropertyCleanupWorkflowInput) -> PropertyCleanupWorkflowResult:
        return await workflow.execute_activity(
            activity_remove_person_property,
            inp,
            start_to_close_timeout=_CLEANUP_ATTEMPT_TIMEOUT,
            heartbeat_timeout=_HEARTBEAT_TIMEOUT,
            retry_policy=_CLEANUP_RETRY,
        )


# ── Coordinator workflow I/O ──────────────────────────────────────────────────


# How many pipelines the daily sweep runs at once. Each one holds a feature matrix in worker memory
# and runs batch queries, so an unbounded sweep overloads ClickHouse and the shared worker.
DEFAULT_COORDINATOR_CONCURRENCY = 4


@frozen
class CoordinatorWorkflowInput:
    # ISO date string; if omitted the workflow uses workflow.now()
    run_date: Optional[str] = None
    # Read from the input, so an operator can change it on the schedule without a deploy.
    max_concurrency: int = DEFAULT_COORDINATOR_CONCURRENCY
    # Set by the catch-up schedule: score again only the pipelines whose scheduled run of the day was lost.
    catch_up: bool = False


@frozen
class CoordinatorWorkflowResult:
    pipelines_processed: int
    pipelines_errored: int
    status: str


@frozen
class LoadActivePipelinesInput:
    # Set in catch-up mode. Discovery then lists only the due pipelines whose scheduled run of this date can retry.
    catch_up_date: Optional[str] = None


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
    validation: ValidationWorkflowResult | BaseException | None,
    kickoff: KickoffTrainingResult | BaseException | None,
) -> PipelineRunOutcome:
    """Classify one pipeline's step results, treating soft-failed activity results as failures too.

    ``None`` is a step the sweep did not start, because the pipeline was not due for scoring, or
    because a catch-up sweep only scores.
    """
    errors: list[str] = []

    if inference is None:
        pass
    elif isinstance(inference, BaseException):
        errors.append(f"inference: {inference}")
    elif inference.status == "failed":
        errors.append(f"inference: {inference.error or 'failed'}")

    if validation is None:
        pass
    elif isinstance(validation, BaseException):
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
    # "explore" | "scheduled" | "not_due" | "manual_only" | "already_running" | "already_ran_today"
    # | "not_eligible" | "tasks_gated" | "no_creator" | "not_launchable" | "rescue_unscorable" | "rescue_throttled"
    reason: str
    error: Optional[str] = None
    # Why an expected skip happened, without counting it as a failure.
    detail: Optional[str] = None


# ── Coordinator activities ────────────────────────────────────────────────────

_COORDINATOR_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5))
_KICKOFF_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=10))
# The iterations of a rescue run, which is shorter than a research run.
RESCUE_ITERATION_BUDGET = 3


@activity.defn(name="autoresearch-coordinator.load_active_pipelines")
def activity_load_active_pipelines(inp: LoadActivePipelinesInput) -> LoadActivePipelinesResult:
    """Return every live pipeline the sweep runs, across every team, and whether each is due for scoring.

    A deactivated organization, or one pending deletion, is left out. A pipeline whose creator no
    longer has access to its team is paused here, before any run is
    dispatched, because every scheduled query and training run acts as the creator. A pipeline
    outside the ``autoresearch`` rollout is skipped but stays live, so it resumes when the rollout
    reaches it again.

    It also fails every inference run that its lost worker left RUNNING.

    The result lists the pipelines that are due and did not score yesterday first, so a bounded
    sweep starts the pipelines that missed a day before the others.

    With ``catch_up_date`` it lists only the due pipelines whose latest scheduled run of that date
    failed with a kind a retry can pass (``scheduled_run_can_retry()``). A pipeline that the daily
    sweep has not reached yet has no run for the date, so the catch-up does not score it twice.
    A catch-up lists nothing while the daily sweep of that date still runs (``activity_mark_daily_sweep``),
    including its kickoff, validation and shadow phases, so the two sweeps never exceed one bound
    together. The next catch-up tick tries again.
    """
    fail_stale_inference_runs()
    if inp.catch_up_date is not None and cache.get(daily_sweep_key(inp.catch_up_date)) == DAILY_SWEEP_RUNNING:
        logger.info("autoresearch_catch_up_deferred", catch_up_date=inp.catch_up_date)
        return LoadActivePipelinesResult(pipelines=[])
    today = django_timezone.now().date()
    yesterday = today - timedelta(days=1)
    # unscoped() because the coordinator's job is exactly to sweep every team. The
    # pipelines it returns carry their team so the downstream activities can scope.
    candidates = (
        AutoresearchPipeline.objects.unscoped()
        .filter(status__in=_LIVE_STATUSES)
        # A null is_active counts as deactivated, as ActiveOrganizationPermission reads it.
        .filter(team__organization__is_active=True)
        .exclude(team__organization__is_pending_deletion=True)
        .select_related("team", "created_by")
        .order_by("created_at")
    )
    pipelines: list[tuple[bool, ActivePipeline]] = []
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
        score_due = last_scored is None or (today - last_scored).days >= pipeline.cadence_days
        if inp.catch_up_date is not None and not (
            score_due
            and scheduled_run_can_retry(
                team_id=pipeline.team_id, pipeline_id=str(pipeline.pk), prediction_date=inp.catch_up_date
            )
        ):
            continue
        missed_yesterday = score_due and (last_scored is None or last_scored < yesterday)
        pipelines.append(
            (
                not missed_yesterday,
                ActivePipeline(pipeline_id=str(pipeline.pk), team_id=pipeline.team_id, score_due=score_due),
            )
        )
    pipelines.sort(key=lambda entry: entry[0])
    return LoadActivePipelinesResult(pipelines=[pipeline for _, pipeline in pipelines])


# The coordinator's execution timeout, which the schedules set. Longer than one pipeline's children
# (inference, then kickoff), shorter than a day, so a stuck coordinator ends before the next tick
# instead of making SKIP drop every later one. The daily sweep marker expires with it.
COORDINATOR_TIMEOUT = timedelta(hours=12)
DAILY_SWEEP_RUNNING = "running"
DAILY_SWEEP_DONE = "done"
# A finished sweep stays marked past the last catch-up tick of its date.
_DAILY_SWEEP_DONE_TTL = timedelta(days=2)


def daily_sweep_key(run_date: str) -> str:
    return f"autoresearch:daily-sweep:{run_date}"


@frozen
class MarkDailySweepInput:
    run_date: str
    state: str


@activity.defn(name="autoresearch-coordinator.mark_daily_sweep")
def activity_mark_daily_sweep(inp: MarkDailySweepInput) -> None:
    """Record that the daily sweep of a date is running or done, so a catch-up waits for it.

    The running marker expires with ``COORDINATOR_TIMEOUT``, so a coordinator that dies without
    marking done holds the catch-up back no longer than it could still run.
    """
    ttl = COORDINATOR_TIMEOUT if inp.state == DAILY_SWEEP_RUNNING else _DAILY_SWEEP_DONE_TTL
    cache.set(daily_sweep_key(inp.run_date), inp.state, timeout=int(ttl.total_seconds()))


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
    """Start a scheduled agent training run, if the pipeline's research schedule says one is due.

    The run row and its task binding commit together under the pipeline row lock, as in the
    facade's ``start_training``, so a manual start cannot interleave. A launch failure raises,
    so the activity retry applies.
    """
    # The gates can call out to billing and flags, so they run before the row lock is taken.
    with team_scope(inp.team_id):
        loaded = AutoresearchPipeline.objects.select_related("created_by", "team__organization").get(pk=inp.pipeline_id)
    if loaded.created_by is not None and (gate := _tasks_gate(loaded)):
        return KickoffTrainingResult(kicked_off=False, reason="tasks_gated", detail=gate)

    with team_scope(inp.team_id), transaction.atomic():
        pipeline = AutoresearchPipeline.objects.select_for_update().get(pk=inp.pipeline_id)

        if pipeline.status != AutoresearchPipeline.Status.RUNNING:
            return KickoffTrainingResult(kicked_off=False, reason="not_eligible")

        if AutoresearchTrainingRun.objects.filter(
            pipeline=pipeline,
            status__in=[AutoresearchTrainingRun.Status.PENDING, AutoresearchTrainingRun.Status.RUNNING],
        ).exists():
            return KickoffTrainingResult(kicked_off=False, reason="already_running")

        # At most one scheduled run per UTC day. A retry after a lost activity response must not
        # launch a second paid run once the first has already ended.
        now = django_timezone.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if AutoresearchTrainingRun.objects.filter(pipeline=pipeline, created_at__gte=today).exists():
            return KickoffTrainingResult(kicked_off=False, reason="already_ran_today")

        schedule = research_schedule(
            research_interval_days=pipeline.research_interval_days,
            pipeline_created_at=pipeline.created_at,
            runs=schedule_runs_for([pipeline.pk], inp.team_id).get(pipeline.pk, []),
        )
        kickoff_reason: AutoresearchTrainingRun.KickoffReason | None = None
        skip_reason = "not_due"
        if pipeline.research_interval_days is None:
            skip_reason = "manual_only"
        elif schedule.phase == "explore":
            kickoff_reason = AutoresearchTrainingRun.KickoffReason.EXPLORE
        elif schedule.is_due(now):
            kickoff_reason = AutoresearchTrainingRun.KickoffReason.SCHEDULED

        # A champion that cannot score stops all predictions, and only a training run can replace
        # it. So a pipeline with no research run due still gets a small rescue run.
        if kickoff_reason is None:
            champion = AutoresearchModel.objects.filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION).first()
            if find_unscorable_champion(champion) is None:
                return KickoffTrainingResult(kicked_off=False, reason=skip_reason)
            # At most one rescue run in each window of UNSCORABLE_AFTER_FAILED_DAYS UTC days, so a
            # pipeline that no candidate can fix costs a bounded amount.
            rescue_window_start = today - timedelta(days=UNSCORABLE_AFTER_FAILED_DAYS - 1)
            if AutoresearchTrainingRun.objects.filter(pipeline=pipeline, created_at__gte=rescue_window_start).exists():
                return KickoffTrainingResult(kicked_off=False, reason="rescue_throttled")
            kickoff_reason = AutoresearchTrainingRun.KickoffReason.RESCUE

        # Training runs in a Tasks sandbox that requires a real owning user. CLI-created
        # pipelines have no creator, so fail here rather than launching a run that would
        # crash in the tasks facade.
        if pipeline.created_by_id is None:
            error = f"Pipeline {inp.pipeline_id} has no creator; training kickoff requires created_by to own the task"
            logger.error(
                "autoresearch_kickoff_training_no_creator",
                pipeline_id=inp.pipeline_id,
            )
            return KickoffTrainingResult(kicked_off=False, reason="no_creator", error=error)

        rescue = kickoff_reason == AutoresearchTrainingRun.KickoffReason.RESCUE
        try:
            with transaction.atomic():
                run_training(
                    pipeline=pipeline,
                    iteration_budget=RESCUE_ITERATION_BUDGET if rescue else pipeline.iterations_per_run,
                    user_id=pipeline.created_by_id,
                    rescue=rescue,
                    kickoff_reason=kickoff_reason,
                )
        except (ValueError, SandboxInferenceError, Action.DoesNotExist) as exc:
            # run_training refuses a departed creator or an unresolvable target before it writes
            # anything. A retry cannot fix either, so these report instead of raising.
            return KickoffTrainingResult(kicked_off=False, reason="not_launchable", error=str(exc))
    if rescue:
        logger.info("autoresearch_kickoff_training_rescue", pipeline_id=inp.pipeline_id)
        return KickoffTrainingResult(kicked_off=True, reason="rescue_unscorable")
    return KickoffTrainingResult(kicked_off=True, reason=kickoff_reason.value)


@frozen
class FailLostInferenceRunsInput:
    pipeline_id: str
    team_id: int
    prediction_date: str
    # The failed child's run id. A catch-up child for the same date has another one, so its live row stays open.
    workflow_run_id: Optional[str] = None


@activity.defn(name="autoresearch-coordinator.fail_lost_inference_runs")
def activity_fail_lost_inference_runs(inp: FailLostInferenceRunsInput) -> int:
    """Fail the scheduled runs that an inference workflow left RUNNING when it ended in an exception."""
    return fail_lost_scheduled_runs(
        team_id=inp.team_id,
        pipeline_id=inp.pipeline_id,
        prediction_date=inp.prediction_date,
        workflow_run_id=inp.workflow_run_id,
    )


def _sweep_access_block(pipeline: AutoresearchPipeline) -> str | None:
    """Why the sweep may no longer act on this pipeline, or None.

    Each activity checks again, because a child can start hours after discovery checked. Load the
    pipeline with ``team__organization`` and ``created_by``.
    """
    organization = pipeline.team.organization
    if not organization.is_active or organization.is_pending_deletion:
        return "The organization is deactivated or pending deletion"
    if pipeline.created_by is None or not has_autoresearch_access(
        pipeline.created_by, team_id=pipeline.team_id, organization_id=str(organization.id)
    ):
        return "Outside the autoresearch rollout"
    return None


def _tasks_gate(pipeline: AutoresearchPipeline) -> str | None:
    """Why the creator may not launch a paid Tasks sandbox now, or None. Mirrors the `/train` gates.

    An unresolvable Desktop access decision raises, so the activity retries instead of launching.
    """
    if blocked := _sweep_access_block(pipeline):
        return blocked
    creator = cast(User, pipeline.created_by)
    organization = pipeline.team.organization
    team_id = pipeline.team_id
    decision = get_desktop_access_decision(creator, organization)
    if not decision.allowed:
        return f"PostHog Desktop access: {decision.value}"
    if task_run_usage_limited(creator, team_id):
        return "The Tasks usage limit is reached"
    return None


# ── Coordinator workflow ──────────────────────────────────────────────────────

# Histories that started before this marker replay the unbounded sweep.
_BOUNDED_SWEEP_PATCH = "autoresearch-bounded-sweep-2026-10"
# Histories that started before this marker do not close the runs of a failed inference child.
_CLOSE_LOST_RUNS_PATCH = "autoresearch-close-lost-runs-2026-10"
# Histories that started before this marker do not tell a catch-up that the daily sweep is running.
_DAILY_SWEEP_MARKER_PATCH = "autoresearch-daily-sweep-marker-2026-10"


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

    At most ``max_concurrency`` pipelines run at once. Each pipeline scores, then kicks off
    training, then validates. Once every champion has scored, the coordinator scores each
    pipeline's shadow set (``activity_run_shadow_scoring``) under the same bound.

    When an inference child ends in an exception, the coordinator fails the runs it left RUNNING.
    A catch-up sweep (``catch_up``) scores again only the pipelines whose scheduled run of the day
    was lost, and skips training kickoff and validation, because the daily sweep already ran them.

    Per-pipeline failures — raised exceptions and
    activity results that report a soft failure — are logged and counted in
    pipelines_errored, but do not prevent other pipelines from running.
    """

    inputs_cls = CoordinatorWorkflowInput

    @workflow.run
    async def run(self, inp: CoordinatorWorkflowInput) -> CoordinatorWorkflowResult:
        run_date = inp.run_date or workflow.now().strftime("%Y-%m-%d")

        workflow.logger.info("autoresearch_coordinator_start", extra={"run_date": run_date})

        tracks_daily_sweep = not inp.catch_up and workflow.patched(_DAILY_SWEEP_MARKER_PATCH)
        if tracks_daily_sweep:
            await _settle(self._mark_daily_sweep(run_date, DAILY_SWEEP_RUNNING))
        try:
            return await self._sweep(inp, run_date)
        finally:
            if tracks_daily_sweep:
                await _settle(self._mark_daily_sweep(run_date, DAILY_SWEEP_DONE))

    def _mark_daily_sweep(self, run_date: str, state: str) -> Awaitable[None]:
        return workflow.execute_activity(
            activity_mark_daily_sweep,
            MarkDailySweepInput(run_date=run_date, state=state),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )

    async def _sweep(self, inp: CoordinatorWorkflowInput, run_date: str) -> CoordinatorWorkflowResult:

        active = await workflow.execute_activity(
            activity_load_active_pipelines,
            LoadActivePipelinesInput(catch_up_date=run_date if inp.catch_up else None),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=_COORDINATOR_RETRY,
        )

        if not active.pipelines:
            workflow.logger.info("autoresearch_coordinator_no_active_pipelines")
            return CoordinatorWorkflowResult(pipelines_processed=0, pipelines_errored=0, status="completed")

        outcomes: list[PipelineRunOutcome | BaseException]
        if workflow.patched(_BOUNDED_SWEEP_PATCH):
            outcomes = await self._run_bounded(active.pipelines, run_date, max(1, inp.max_concurrency), inp.catch_up)
        else:
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

    async def _run_bounded(
        self, pipelines: list[ActivePipeline], run_date: str, concurrency: int, catch_up: bool
    ) -> list[PipelineRunOutcome | BaseException]:
        """Run every pipeline with at most ``concurrency`` in flight, then every shadow set under the same bound."""
        slots = _asyncio.Semaphore(concurrency)

        async def bounded(step: Callable[[], Awaitable[_T]]) -> _T:
            async with slots:
                return await step()

        sweeps = await _asyncio.gather(
            *[bounded(partial(self._run_pipeline_in_sequence, p, run_date, concurrency, catch_up)) for p in pipelines],
            return_exceptions=True,
        )
        # Shadow scoring starts only after every champion has finished, so champions free their memory first.
        shadows = [
            (pipeline, sweep.inference.run_id)
            for pipeline, sweep in zip(pipelines, sweeps)
            if isinstance(sweep, _PipelineSweep)
            and sweep.inference is not None
            and sweep.inference.status == "completed"
            and sweep.inference.run_id
        ]
        shadow_results = await _asyncio.gather(
            *[bounded(partial(self._score_shadows, p, r)) for p, r in shadows],
            return_exceptions=True,
        )
        for (pipeline, _), result in zip(shadows, shadow_results):
            if isinstance(result, BaseException):
                workflow.logger.warning(
                    "autoresearch_shadow_scoring_failed",
                    extra={"pipeline_id": pipeline.pipeline_id, "error": str(result)},
                )
        return [sweep if isinstance(sweep, BaseException) else sweep.outcome for sweep in sweeps]

    async def _run_pipeline_in_sequence(
        self, pipeline: ActivePipeline, run_date: str, concurrency: int, catch_up: bool
    ) -> _PipelineSweep:
        """On a cadence day score, then kick off training. Then validate. One step at a time, so a pipeline holds one slot.

        A catch-up sweep only scores.
        """
        pipeline_id = pipeline.pipeline_id
        inference_result: InferenceWorkflowResult | BaseException | None = None
        validation_result: ValidationWorkflowResult | BaseException | None = None
        kickoff_result: KickoffTrainingResult | BaseException | None = None
        if pipeline.score_due:
            inference_result = await _settle(
                workflow.execute_child_workflow(
                    AutoresearchInferenceWorkflow.run,
                    InferenceWorkflowInput(
                        pipeline_id=pipeline_id,
                        team_id=pipeline.team_id,
                        prediction_date=run_date,
                        defer_shadows=True,
                        coordinator_concurrency=concurrency,
                    ),
                    id=inference_workflow_id(pipeline_id, run_date),
                    execution_timeout=INFERENCE_WORKFLOW_TIMEOUT,
                    # A catch-up starts only after the daily sweep's child for the date failed or timed out.
                    id_reuse_policy=(
                        WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
                        if catch_up
                        else WorkflowIDReusePolicy.ALLOW_DUPLICATE
                    ),
                )
            )
            # A child that failed to start (it is already running) is not a ChildWorkflowError, so its runs stay open.
            if isinstance(inference_result, ChildWorkflowError) and workflow.patched(_CLOSE_LOST_RUNS_PATCH):
                await _settle(self._fail_lost_runs(pipeline, run_date, inference_result.run_id))
            if not catch_up:
                kickoff_result = await _settle(self._kickoff(pipeline))
        if not catch_up:
            validation_result = await _settle(self._validate(pipeline, run_date))
        outcome = self._evaluate(pipeline_id, inference_result, validation_result, kickoff_result)
        return _PipelineSweep(
            outcome=outcome,
            inference=inference_result if isinstance(inference_result, InferenceWorkflowResult) else None,
        )

    async def _score_shadows(self, pipeline: ActivePipeline, run_id: str) -> RunShadowScoringResult:
        return await workflow.execute_activity(
            activity_run_shadow_scoring,
            RunShadowScoringInput(pipeline_id=pipeline.pipeline_id, team_id=pipeline.team_id, run_id=run_id),
            start_to_close_timeout=_SHADOW_ATTEMPT_TIMEOUT,
            heartbeat_timeout=_HEARTBEAT_TIMEOUT,
            retry_policy=_SHADOW_RETRY,
        )

    def _fail_lost_runs(self, pipeline: ActivePipeline, run_date: str, workflow_run_id: str) -> Awaitable[int]:
        return workflow.execute_activity(
            activity_fail_lost_inference_runs,
            FailLostInferenceRunsInput(
                pipeline_id=pipeline.pipeline_id,
                team_id=pipeline.team_id,
                prediction_date=run_date,
                workflow_run_id=workflow_run_id,
            ),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )

    def _validate(self, pipeline: ActivePipeline, run_date: str) -> Awaitable[ValidationWorkflowResult]:
        return workflow.execute_child_workflow(
            AutoresearchValidationWorkflow.run,
            ValidationWorkflowInput(pipeline_id=pipeline.pipeline_id, team_id=pipeline.team_id),
            id=f"autoresearch-validation-{pipeline.pipeline_id}-{run_date}",
            execution_timeout=_VALIDATION_WORKFLOW_TIMEOUT,
        )

    def _kickoff(self, pipeline: ActivePipeline) -> Awaitable[KickoffTrainingResult]:
        return workflow.execute_activity(
            activity_kickoff_training,
            KickoffTrainingInput(pipeline_id=pipeline.pipeline_id, team_id=pipeline.team_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=_KICKOFF_RETRY,
        )

    def _evaluate(
        self,
        pipeline_id: str,
        inference: InferenceWorkflowResult | BaseException | None,
        validation: ValidationWorkflowResult | BaseException | None,
        kickoff: KickoffTrainingResult | BaseException | None,
    ) -> PipelineRunOutcome:
        outcome = evaluate_pipeline_outcome(
            pipeline_id=pipeline_id, inference=inference, validation=validation, kickoff=kickoff
        )
        for error in outcome.errors:
            workflow.logger.warning(
                "autoresearch_pipeline_step_failed",
                extra={"pipeline_id": pipeline_id, "error": error},
            )
        return outcome

    async def _run_pipeline(self, pipeline: ActivePipeline, run_date: str) -> PipelineRunOutcome:
        """The unbounded sweep, kept for histories that started before ``_BOUNDED_SWEEP_PATCH``.

        Runs validation, and on a cadence day inference then training kickoff, for one pipeline.
        """
        pipeline_id = pipeline.pipeline_id
        validation = _settle(self._validate(pipeline, run_date))
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
                        id=inference_workflow_id(pipeline_id, run_date),
                        execution_timeout=INFERENCE_WORKFLOW_TIMEOUT,
                    )
                ),
            )
            kickoff_result = await _settle(self._kickoff(pipeline))
        else:
            validation_result = await validation
        return self._evaluate(pipeline_id, inference_result, validation_result, kickoff_result)


@frozen
class _PipelineSweep:
    outcome: PipelineRunOutcome
    # The champion's result, so the shadow phase knows which runs to score against.
    inference: InferenceWorkflowResult | None


async def _settle(awaitable: Awaitable[_T]) -> _T | BaseException:
    """Return a step's exception instead of raising it, so one failed step does not end the others."""
    try:
        return await awaitable
    except Exception as exc:
        return exc
