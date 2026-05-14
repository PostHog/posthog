"""Business logic for AutoML.

Validation, queries, and state transitions live here.
The facade is a thin layer that calls into this module and
converts ORM models to frozen dataclasses.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from django.db import transaction

from ..facade import contracts
from ..facade.enums import ModelRole, PipelineStatus, RunKind, RunStatus
from ..models import AutoMLModelVersion, AutoMLPipeline, AutoMLPipelineRun
from .validation import run_validation

__all__ = [
    "create_pipeline",
    "list_pipelines",
    "get_pipeline",
    "update_pipeline",
    "transition_pipeline",
    "set_runtime",
    "run_validation",
    "record_training_result",
    "list_model_versions",
    "get_active_model",
    "promote_to_champion",
    "create_pipeline_run",
    "get_pipeline_run",
    "list_pipeline_runs",
    "record_eda_result",
    "record_bootstrap_outcome",
    "mark_run_failed",
    "find_latest_winning_run",
]

# Allowed status transitions: source -> set of allowed destinations.
# Lifecycle helpers below funnel writes through this map so the state
# machine stays explicit.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    PipelineStatus.DRAFT.value: {PipelineStatus.BOOTSTRAP_PENDING.value, PipelineStatus.ARCHIVED.value},
    PipelineStatus.BOOTSTRAP_PENDING.value: {
        PipelineStatus.BOOTSTRAP_RUNNING.value,
        # Direct to ACTIVE when the run records a successful outcome with a champion —
        # we don't pass through BOOTSTRAP_RUNNING because there's no separate runtime
        # state for the agent's mid-flight phase yet (the run row tracks that already).
        PipelineStatus.ACTIVE.value,
        PipelineStatus.PAUSED.value,
        PipelineStatus.ARCHIVED.value,
        PipelineStatus.FAILED.value,
    },
    PipelineStatus.BOOTSTRAP_RUNNING.value: {
        PipelineStatus.ACTIVE.value,
        PipelineStatus.FAILED.value,
        PipelineStatus.PAUSED.value,
    },
    PipelineStatus.ACTIVE.value: {PipelineStatus.PAUSED.value, PipelineStatus.ARCHIVED.value},
    PipelineStatus.PAUSED.value: {PipelineStatus.ACTIVE.value, PipelineStatus.ARCHIVED.value},
    PipelineStatus.FAILED.value: {PipelineStatus.BOOTSTRAP_PENDING.value, PipelineStatus.ARCHIVED.value},
    PipelineStatus.ARCHIVED.value: set(),
}


def create_pipeline(
    *,
    team_id: int,
    params: contracts.CreatePipelineInput,
    created_by_id: int | None = None,
) -> AutoMLPipeline:
    """Persist a new pipeline in draft state.

    Setup-time validation (volume, base rate, leakage) lands as a separate
    ``automl-validate`` facade method once we have checks against real data.
    """
    return AutoMLPipeline.objects.create(
        team_id=team_id,
        name=params.name,
        description=params.description,
        task_type=params.task_type.value,
        status=PipelineStatus.DRAFT.value,
        autonomy=params.autonomy.value,
        config=params.config,
        training_population=params.training_population,
        inference_population=params.inference_population,
        inference_cadence=params.inference_cadence.value,
        retraining_cadence=params.retraining_cadence.value,
        output_property_name=params.output_property_name,
        created_by_id=created_by_id,
    )


def list_pipelines(*, team_id: int) -> list[AutoMLPipeline]:
    """List all non-archived pipelines for a team, newest first."""
    return list(
        AutoMLPipeline.objects.filter(team_id=team_id)
        .exclude(status=PipelineStatus.ARCHIVED.value)
        .order_by("-created_at")
    )


def get_pipeline(*, team_id: int, pipeline_id: UUID) -> AutoMLPipeline | None:
    """Fetch one pipeline by ID, scoped to a team."""
    return AutoMLPipeline.objects.filter(team_id=team_id, id=pipeline_id).first()


def update_pipeline(
    *,
    team_id: int,
    pipeline_id: UUID,
    params: contracts.UpdatePipelineInput,
) -> AutoMLPipeline | None:
    """Apply partial config updates. Status transitions go through transition_pipeline."""
    pipeline = get_pipeline(team_id=team_id, pipeline_id=pipeline_id)
    if pipeline is None:
        return None

    dirty = False
    if params.name is not None:
        pipeline.name = params.name
        dirty = True
    if params.description is not None:
        pipeline.description = params.description
        dirty = True
    if params.autonomy is not None:
        pipeline.autonomy = params.autonomy.value
        dirty = True
    if params.inference_cadence is not None:
        pipeline.inference_cadence = params.inference_cadence.value
        dirty = True
    if params.retraining_cadence is not None:
        pipeline.retraining_cadence = params.retraining_cadence.value
        dirty = True
    if params.output_property_name is not None:
        pipeline.output_property_name = params.output_property_name
        dirty = True
    if params.config is not None:
        pipeline.config = params.config
        dirty = True
    if params.training_population is not None:
        pipeline.training_population = params.training_population
        dirty = True
    if params.inference_population is not None:
        pipeline.inference_population = params.inference_population
        dirty = True

    if dirty:
        pipeline.save()
    return pipeline


def transition_pipeline(
    *,
    team_id: int,
    pipeline_id: UUID,
    new_status: PipelineStatus,
) -> AutoMLPipeline:
    """Transition a pipeline's status, raising on disallowed moves.

    Raises ``PipelineNotFoundError`` if the pipeline doesn't exist or
    ``PipelineStateTransitionError`` if the transition isn't permitted
    from the current state.
    """
    pipeline = get_pipeline(team_id=team_id, pipeline_id=pipeline_id)
    if pipeline is None:
        raise contracts.PipelineNotFoundError(f"pipeline {pipeline_id} not found in team {team_id}")

    if new_status.value not in _ALLOWED_TRANSITIONS.get(pipeline.status, set()):
        raise contracts.PipelineStateTransitionError(
            f"cannot transition from {pipeline.status!r} to {new_status.value!r}",
        )

    pipeline.status = new_status.value
    pipeline.save(update_fields=["status", "updated_at"])
    return pipeline


def set_runtime(*, pipeline: AutoMLPipeline, **updates: Any) -> AutoMLPipeline:
    """Merge keys into the pipeline's `runtime` JSON and persist.

    `runtime` is system-managed (bootstrap_task_id, bootstrap_error,
    last_inference_at, ...). Model version pointers live on
    ``AutoMLModelVersion.role`` instead. User-configured intent lives in
    `config` — never touch that from runtime paths.
    """
    pipeline.runtime = {**pipeline.runtime, **updates}
    pipeline.save(update_fields=["runtime", "updated_at"])
    return pipeline


def record_training_result(
    *,
    team_id: int,
    pipeline_id: UUID,
    params: contracts.RecordTrainingResultInput,
    run_id: UUID | None = None,
) -> AutoMLModelVersion:
    """Persist one trained model version on a pipeline.

    Looks the pipeline up scoped to the team so cross-team writes fail closed.
    Default role is challenger — promotion to champion is a separate explicit
    step via ``promote_to_champion`` (and never happens implicitly here).

    When ``run_id`` is provided, the matching ``AutoMLPipelineRun`` is
    updated in the same transaction: ``created_model_version_id`` points at
    the new version and ``training_result`` gets a compact denormalized
    summary (metrics, top-5 leaderboard rows, eval_metric) so the
    pipeline-detail run history doesn't need to join across tables to
    render. Same-pipeline / same-team scoping is enforced so a leaked
    ``run_id`` can't be coaxed into writing the wrong record.
    """
    pipeline = get_pipeline(team_id=team_id, pipeline_id=pipeline_id)
    if pipeline is None:
        raise contracts.PipelineNotFoundError(f"pipeline {pipeline_id} not found in team {team_id}")

    with transaction.atomic():
        version = AutoMLModelVersion.objects.create(
            team_id=team_id,
            pipeline=pipeline,
            role=params.role.value,
            metrics=params.metrics,
            leaderboard=params.leaderboard,
            training_params=params.training_params,
            tracking_metadata=params.tracking_metadata,
            eval_metric=params.eval_metric,
            problem_type=params.problem_type,
            artifact_uri=params.artifact_uri,
            features_hash=params.features_hash,
            rows_train=params.rows_train,
            rows_val=params.rows_val,
            rows_test=params.rows_test,
            training_task_id=params.training_task_id,
        )

        if run_id is not None:
            run = AutoMLPipelineRun.objects.filter(team_id=team_id, pipeline_id=pipeline_id, id=run_id).first()
            if run is None:
                raise contracts.PipelineRunNotFoundError(
                    f"run {run_id} not found for pipeline {pipeline_id} in team {team_id}"
                )
            run.created_model_version_id = version.id
            run.training_result = {
                "metrics": params.metrics,
                # Keep the denormalized summary compact — the full leaderboard
                # lives on AutoMLModelVersion. Top 5 is enough for the
                # pipeline-detail run history's at-a-glance render.
                "leaderboard_top5": params.leaderboard[:5],
                "eval_metric": params.eval_metric,
                "problem_type": params.problem_type,
            }
            run.save(update_fields=["created_model_version_id", "training_result", "updated_at"])

        return version


def list_model_versions(*, team_id: int, pipeline_id: UUID) -> list[AutoMLModelVersion]:
    """List every model version for a pipeline, newest first.

    Returns archived versions too — they're part of the audit trail and `$model_version_id`
    on past predictions still needs to resolve.
    """
    return list(AutoMLModelVersion.objects.filter(team_id=team_id, pipeline_id=pipeline_id).order_by("-created_at"))


def get_active_model(
    *,
    team_id: int,
    pipeline_id: UUID,
    role: ModelRole,
) -> AutoMLModelVersion | None:
    """Fetch the version currently holding a role on a pipeline.

    The partial unique constraint enforces at-most-one active version per
    (pipeline, role) so `.first()` is the only possible answer.
    """
    return AutoMLModelVersion.objects.filter(team_id=team_id, pipeline_id=pipeline_id, role=role.value).first()


def promote_to_champion(*, team_id: int, model_version_id: UUID) -> AutoMLModelVersion:
    """Make ``model_version_id`` the champion for its pipeline.

    Atomic: in one transaction, the current champion (if any and different)
    is archived first, then the target version's role is set to champion.
    The partial unique constraint on (pipeline, role) means concurrent
    promotions to the same pipeline fail-closed at the DB layer rather than
    racing to two champions.

    No-op if the target is already the champion. Promotion from any starting
    role is allowed (challenger → champion, archived → champion) — the
    audit trail comes from the archived row, not from the transition path.
    """
    with transaction.atomic():
        target = AutoMLModelVersion.objects.select_for_update().filter(team_id=team_id, id=model_version_id).first()
        if target is None:
            raise contracts.ModelVersionNotFoundError(f"model version {model_version_id} not found in team {team_id}")

        if target.role == ModelRole.CHAMPION.value:
            return target

        current_champion = (
            AutoMLModelVersion.objects.select_for_update()
            .filter(team_id=team_id, pipeline_id=target.pipeline_id, role=ModelRole.CHAMPION.value)
            .first()
        )
        if current_champion is not None and current_champion.id != target.id:
            current_champion.role = ModelRole.ARCHIVED.value
            current_champion.save(update_fields=["role", "updated_at"])

        target.role = ModelRole.CHAMPION.value
        target.save(update_fields=["role", "updated_at"])
        return target


# ---- Pipeline-run lifecycle ----
#
# Bootstrap / retrain / inference runs each get one `AutoMLPipelineRun` row.
# Created up-front (status=running) by the surrounding lifecycle helper (e.g.
# `bootstrap.enqueue_bootstrap_training`); progressively populated by the
# agent's MCP checkpoints; flipped to a terminal state by `record_bootstrap_outcome`
# or `mark_run_failed`. See `io-spec.md`'s "Per pipeline run (durable record)".


def create_pipeline_run(
    *,
    team_id: int,
    pipeline_id: UUID,
    params: contracts.CreatePipelineRunInput,
) -> AutoMLPipelineRun:
    """Open a new run row for a pipeline. Always starts in ``status=running``.

    Looks the pipeline up scoped to the team so cross-team writes fail closed.
    Pipelines that exist but already have an in-progress run are still allowed
    to open another — the retraining loop relies on chained runs.
    """
    pipeline = get_pipeline(team_id=team_id, pipeline_id=pipeline_id)
    if pipeline is None:
        raise contracts.PipelineNotFoundError(f"pipeline {pipeline_id} not found in team {team_id}")

    return AutoMLPipelineRun.objects.create(
        team_id=team_id,
        pipeline=pipeline,
        run_kind=params.run_kind.value,
        task_slug=params.task_slug,
        task_workspace_root=params.task_workspace_root,
        task_id=params.task_id,
        parent_run_id=params.parent_run_id,
    )


def get_pipeline_run(*, team_id: int, run_id: UUID) -> AutoMLPipelineRun | None:
    """Fetch one run by ID, scoped to a team. Returns ``None`` when not found."""
    return AutoMLPipelineRun.objects.filter(team_id=team_id, id=run_id).first()


def list_pipeline_runs(*, team_id: int, pipeline_id: UUID) -> list[AutoMLPipelineRun]:
    """List every run for a pipeline, newest first. No status filter — the
    pipeline-detail page shows the full timeline including failures."""
    return list(AutoMLPipelineRun.objects.filter(team_id=team_id, pipeline_id=pipeline_id).order_by("-started_at"))


def record_eda_result(
    *,
    team_id: int,
    run_id: UUID,
    params: contracts.RecordEdaResultInput,
) -> AutoMLPipelineRun:
    """Stash the agent's EDA output on an in-progress run.

    Called after `automl eda --task <slug>` completes but before training
    starts. The `eda_result` shape is whatever the CLI's `eda.yaml` plus
    stdout JSON give us — kept JSON for schemaless evolution. ``cli_run_id``
    is also persisted now so the workspace's `runs/<run_id>/` path is
    addressable from the row alone.
    """
    run = get_pipeline_run(team_id=team_id, run_id=run_id)
    if run is None:
        raise contracts.PipelineRunNotFoundError(f"run {run_id} not found in team {team_id}")

    run.eda_result = params.eda_result
    update_fields = ["eda_result", "updated_at"]
    if params.cli_run_id:
        run.cli_run_id = params.cli_run_id
        update_fields.append("cli_run_id")
    run.save(update_fields=update_fields)
    return run


def record_bootstrap_outcome(
    *,
    team_id: int,
    run_id: UUID,
    params: contracts.RecordBootstrapOutcomeInput,
) -> AutoMLPipelineRun:
    """Flip a run to a terminal state and write the agent's final outcome report.

    Accepts ``status=succeeded`` / ``failed`` / ``aborted`` — ``running`` is
    rejected because that's an open-state hint, not a terminal one. The
    write is single-shot: once a run reaches a terminal state, this method
    no-ops (it returns the already-terminal row). That's deliberate — a
    misbehaving agent can't repeatedly overwrite the outcome and the
    pipeline-detail page's timeline stays stable.
    """
    if params.status == RunStatus.RUNNING:
        raise ValueError("record_bootstrap_outcome requires a terminal status")

    run = get_pipeline_run(team_id=team_id, run_id=run_id)
    if run is None:
        raise contracts.PipelineRunNotFoundError(f"run {run_id} not found in team {team_id}")

    if run.status != RunStatus.RUNNING.value:
        # Already terminal — no-op. We don't raise: the agent may retry the
        # MCP call after a transient network blip, and idempotent behavior
        # is friendlier than a 409.
        return run

    with transaction.atomic():
        run.status = params.status.value
        run.outcome_report = params.outcome_report
        run.failure_reason = params.failure_reason
        if params.cli_run_id:
            run.cli_run_id = params.cli_run_id
        if params.agent_session_id:
            run.agent_session_id = params.agent_session_id
        run.completed_at = datetime.now(UTC)
        run.save(
            update_fields=[
                "status",
                "outcome_report",
                "failure_reason",
                "cli_run_id",
                "agent_session_id",
                "completed_at",
                "updated_at",
            ]
        )

        # Pipeline-state reconciliation only applies to bootstrap runs — that's
        # the run that owns the DRAFT → ACTIVE / DRAFT → FAILED transition.
        # Retrain runs leave pipeline status alone (the pipeline is already
        # ACTIVE while iterating); inference runs same.
        if run.run_kind == RunKind.BOOTSTRAP.value:
            pipeline = run.pipeline  # FK in-memory; safe to dereference here
            if params.status == RunStatus.SUCCEEDED and run.created_model_version_id:
                # Bootstrap landed a champion. Lift the pipeline into ACTIVE so
                # scheduled inference + retraining can begin.
                if pipeline.status == PipelineStatus.BOOTSTRAP_PENDING.value:
                    pipeline.status = PipelineStatus.ACTIVE.value
                    pipeline.save(update_fields=["status", "updated_at"])
            elif params.status in (RunStatus.FAILED, RunStatus.ABORTED):
                # Bootstrap bailed without a champion. Lift the pipeline into
                # FAILED so the user can see why and retry via `start`.
                if pipeline.status == PipelineStatus.BOOTSTRAP_PENDING.value:
                    pipeline.status = PipelineStatus.FAILED.value
                    pipeline.save(update_fields=["status", "updated_at"])

    return run


def record_inference_outcome(
    *,
    team_id: int,
    run_id: UUID,
    params: contracts.RecordInferenceOutcomeInput,
) -> AutoMLPipelineRun:
    """Flip an inference run to a terminal state and stamp the CLI manifest onto it.

    Same idempotent shape as ``record_bootstrap_outcome``: ``running`` is
    rejected (terminal status required); calling on an already-terminal run
    no-ops and returns the existing row. The ``inference_result`` JSON
    field receives the full ``refresh-task`` stdout manifest unchanged.

    Pipeline status reconciliation does NOT happen here — an inference
    failure doesn't fail the pipeline (the champion keeps serving; the
    next scheduled run will retry). The pipeline stays ``ACTIVE``.

    Raises ``PipelineRunNotFoundError`` if the run doesn't exist on the team
    and ``ValueError`` if the run isn't an ``INFERENCE`` run (guards against
    accidental wiring — bootstrap / retrain runs have their own outcome
    handlers).
    """
    if params.status == RunStatus.RUNNING:
        raise ValueError("record_inference_outcome requires a terminal status")

    run = get_pipeline_run(team_id=team_id, run_id=run_id)
    if run is None:
        raise contracts.PipelineRunNotFoundError(f"run {run_id} not found in team {team_id}")

    if run.run_kind != RunKind.INFERENCE.value:
        raise ValueError(
            f"record_inference_outcome called on a {run.run_kind!r} run; "
            f"use record_bootstrap_outcome for bootstrap and retrain runs."
        )

    if run.status != RunStatus.RUNNING.value:
        return run

    with transaction.atomic():
        run.status = params.status.value
        run.outcome_report = params.outcome_report
        run.failure_reason = params.failure_reason
        run.inference_result = params.inference_result
        if params.agent_session_id:
            run.agent_session_id = params.agent_session_id
        run.completed_at = datetime.now(UTC)
        run.save(
            update_fields=[
                "status",
                "outcome_report",
                "failure_reason",
                "inference_result",
                "agent_session_id",
                "completed_at",
                "updated_at",
            ]
        )

    return run


def find_latest_winning_run(*, team_id: int, pipeline_id: UUID) -> AutoMLPipelineRun | None:
    """Find the most recent succeeded run on a pipeline that landed a model version.

    Used by the retraining flow to pick the `parent_run_id` — the run whose
    recipe we're iterating on. Excludes runs that finished but never produced
    a version (e.g., the agent bailed before training). Returns ``None`` if no
    winning run exists (pipeline hasn't bootstrapped a champion yet).
    """
    return (
        AutoMLPipelineRun.objects.filter(
            team_id=team_id,
            pipeline_id=pipeline_id,
            status=RunStatus.SUCCEEDED.value,
            created_model_version_id__isnull=False,
        )
        .order_by("-completed_at")
        .first()
    )


def mark_run_failed(
    *,
    run: AutoMLPipelineRun,
    failure_reason: str,
) -> AutoMLPipelineRun:
    """Mark a run as failed when the failure originates outside the agent.

    Called by the surrounding workflow when something blew up before the
    agent could write its own outcome report — e.g. `Task.create_and_run`
    raises, the sandbox refuses to provision, or the Temporal workflow
    self-cancels. Idempotent: no-op if the run is already terminal.
    """
    if run.status != RunStatus.RUNNING.value:
        return run

    run.status = RunStatus.FAILED.value
    run.failure_reason = failure_reason
    run.completed_at = datetime.now(UTC)
    run.save(update_fields=["status", "failure_reason", "completed_at", "updated_at"])
    return run
