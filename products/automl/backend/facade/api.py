"""
Facade for AutoML.

The ONLY module other products are allowed to import. Accepts
frozen dataclasses, calls logic/, returns frozen dataclasses.
Never returns ORM instances or imports DRF.
"""

from __future__ import annotations

from uuid import UUID

from .. import logic
from ..models import AutoMLModelVersion, AutoMLPipeline, AutoMLPipelineRun
from ..training import (
    bootstrap,
    retrain as retrain_training,
)
from . import contracts
from .enums import AutonomyLevel, Cadence, ModelRole, PipelineStatus, RunKind, RunStatus, TaskType

# Re-export domain exceptions so callers don't have to dig into contracts.
PipelineNotFoundError = contracts.PipelineNotFoundError
PipelineStateTransitionError = contracts.PipelineStateTransitionError
ModelVersionNotFoundError = contracts.ModelVersionNotFoundError
PipelineRunNotFoundError = contracts.PipelineRunNotFoundError
RetrainNotApplicableError = contracts.RetrainNotApplicableError


def _run_to_dto(obj: AutoMLPipelineRun) -> contracts.AutoMLPipelineRunDTO:
    return contracts.AutoMLPipelineRunDTO(
        id=obj.id,
        pipeline_id=obj.pipeline_id,  # type: ignore[attr-defined]
        team_id=obj.team_id,
        run_kind=RunKind(obj.run_kind),
        status=RunStatus(obj.status),
        task_slug=obj.task_slug,
        task_workspace_root=obj.task_workspace_root,
        cli_run_id=obj.cli_run_id,
        agent_session_id=obj.agent_session_id,
        task_id=obj.task_id,
        started_at=obj.started_at,
        completed_at=obj.completed_at,
        outcome_report=obj.outcome_report,
        eda_result=obj.eda_result,
        training_result=obj.training_result,
        failure_reason=obj.failure_reason,
        created_model_version_id=obj.created_model_version_id,
        parent_run_id=obj.parent_run_id,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


def _version_to_dto(obj: AutoMLModelVersion) -> contracts.AutoMLModelVersionDTO:
    return contracts.AutoMLModelVersionDTO(
        id=obj.id,
        pipeline_id=obj.pipeline_id,  # type: ignore[attr-defined]
        team_id=obj.team_id,
        role=ModelRole(obj.role),
        metrics=obj.metrics,
        leaderboard=obj.leaderboard,
        training_params=obj.training_params,
        tracking_metadata=obj.tracking_metadata,
        eval_metric=obj.eval_metric,
        problem_type=obj.problem_type,
        artifact_uri=obj.artifact_uri,
        features_hash=obj.features_hash,
        rows_train=obj.rows_train,
        rows_val=obj.rows_val,
        rows_test=obj.rows_test,
        training_task_id=obj.training_task_id,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


def _to_dto(obj: AutoMLPipeline) -> contracts.AutoMLPipelineDTO:
    return contracts.AutoMLPipelineDTO(
        id=obj.id,
        team_id=obj.team_id,
        name=obj.name,
        description=obj.description,
        task_type=TaskType(obj.task_type),
        status=PipelineStatus(obj.status),
        autonomy=AutonomyLevel(obj.autonomy),
        config=obj.config,
        training_population=obj.training_population,
        inference_population=obj.inference_population,
        inference_cadence=Cadence(obj.inference_cadence),
        retraining_cadence=Cadence(obj.retraining_cadence),
        output_property_name=obj.output_property_name,
        runtime=obj.runtime,
        created_by_id=obj.created_by_id,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


def create(
    *,
    team_id: int,
    params: contracts.CreatePipelineInput,
    created_by_id: int | None = None,
) -> contracts.AutoMLPipelineDTO:
    """Create a new pipeline in draft state."""
    obj = logic.create_pipeline(team_id=team_id, params=params, created_by_id=created_by_id)
    return _to_dto(obj)


def list_for_team(*, team_id: int) -> list[contracts.AutoMLPipelineDTO]:
    """List non-archived pipelines for the team, newest first."""
    return [_to_dto(obj) for obj in logic.list_pipelines(team_id=team_id)]


def get(*, team_id: int, pipeline_id: UUID) -> contracts.AutoMLPipelineDTO | None:
    """Get one pipeline by ID. Returns None when not found."""
    obj = logic.get_pipeline(team_id=team_id, pipeline_id=pipeline_id)
    return _to_dto(obj) if obj else None


def update(
    *,
    team_id: int,
    pipeline_id: UUID,
    params: contracts.UpdatePipelineInput,
) -> contracts.AutoMLPipelineDTO | None:
    """Apply partial config updates. Status transitions use ``start`` / ``pause`` / ``resume`` / ``archive`` instead."""
    obj = logic.update_pipeline(team_id=team_id, pipeline_id=pipeline_id, params=params)
    return _to_dto(obj) if obj else None


def start(*, team_id: int, pipeline_id: UUID, user_id: int) -> contracts.AutoMLPipelineDTO:
    """Transition a draft pipeline to BOOTSTRAP_PENDING and enqueue training.

    Three-phase:
      1. State transition (DRAFT/FAILED -> BOOTSTRAP_PENDING). Fails fast on
         disallowed moves via ``PipelineStateTransitionError``.
      2. Open an ``AutoMLPipelineRun`` row in ``status=running`` with the
         task slug and workspace pre-pinned. The agent uses ``run_id`` on
         every ``automl-record-*`` MCP call so the same row accumulates EDA,
         training, and outcome updates.
      3. Enqueue the orchestrating Task. On enqueue failure both the
         pipeline and the run flip to a failed state, and the error is
         stashed in ``runtime.bootstrap_error`` so the user can retry.

    The Task's id lands on the pipeline as ``runtime.bootstrap_task_id`` and
    on the run row as ``task_id``. Returns the post-enqueue DTO.
    """
    obj = logic.transition_pipeline(
        team_id=team_id, pipeline_id=pipeline_id, new_status=PipelineStatus.BOOTSTRAP_PENDING
    )

    task_slug = bootstrap.derive_task_slug(obj)
    task_workspace_root = bootstrap.derive_task_workspace_root(task_slug)

    run = logic.create_pipeline_run(
        team_id=team_id,
        pipeline_id=pipeline_id,
        params=contracts.CreatePipelineRunInput(
            run_kind=RunKind.BOOTSTRAP,
            task_slug=task_slug,
            task_workspace_root=task_workspace_root,
        ),
    )

    try:
        task = bootstrap.enqueue_bootstrap_training(
            pipeline=obj,
            user_id=user_id,
            run_id=run.id,
            task_slug=task_slug,
            task_workspace_root=task_workspace_root,
        )
    except Exception as exc:
        # Surface the failure so the user can retry. Use str(exc) only — the
        # full traceback stays in logs, not in user-visible runtime state.
        logic.mark_run_failed(run=run, failure_reason="task_create_failed")
        logic.set_runtime(pipeline=obj, bootstrap_error=str(exc))
        logic.transition_pipeline(team_id=team_id, pipeline_id=pipeline_id, new_status=PipelineStatus.FAILED)
        raise

    # Wire the task id onto the run row so the pipeline-detail page and any
    # ops queries (find the Task for this run) can navigate either direction.
    run.task_id = task.id
    run.save(update_fields=["task_id", "updated_at"])

    obj = logic.set_runtime(pipeline=obj, bootstrap_task_id=str(task.id))
    return _to_dto(obj)


def retrain(*, team_id: int, pipeline_id: UUID, user_id: int) -> contracts.AutoMLPipelineRunDTO:
    """Dispatch a retraining iteration for an active pipeline.

    Preconditions:
      - Pipeline must be ``ACTIVE``. Retraining doesn't apply to bootstrap-pending
        or failed pipelines — those need ``start`` first.
      - A previous winning run must exist (something to iterate on). If none,
        raises ``RetrainNotApplicableError``.

    Three-phase, mirroring ``start``:
      1. Find the parent run (latest succeeded run with a model version).
      2. Open an ``AutoMLPipelineRun`` row with ``run_kind=RETRAIN`` and
         ``parent_run_id`` pointing at the parent.
      3. Enqueue the orchestrating Task. On enqueue failure the run flips to
         ``failed`` with ``failure_reason=task_create_failed``; the pipeline
         stays ``ACTIVE`` (retraining failures don't fail the pipeline — the
         champion keeps serving).

    Returns the run DTO (not the pipeline DTO) — the user is dispatching a
    new run, not changing pipeline state, so the run is what matters.
    """
    pipeline = logic.get_pipeline(team_id=team_id, pipeline_id=pipeline_id)
    if pipeline is None:
        raise contracts.PipelineNotFoundError(f"pipeline {pipeline_id} not found in team {team_id}")
    if pipeline.status != PipelineStatus.ACTIVE.value:
        raise contracts.RetrainNotApplicableError(
            f"cannot retrain pipeline in status {pipeline.status!r}; must be ACTIVE"
        )

    parent_run = logic.find_latest_winning_run(team_id=team_id, pipeline_id=pipeline_id)
    if parent_run is None:
        raise contracts.RetrainNotApplicableError(
            "no winning run on this pipeline yet — bootstrap a first model before retraining"
        )

    task_slug = bootstrap.derive_task_slug(pipeline)
    task_workspace_root = bootstrap.derive_task_workspace_root(task_slug)

    run = logic.create_pipeline_run(
        team_id=team_id,
        pipeline_id=pipeline_id,
        params=contracts.CreatePipelineRunInput(
            run_kind=RunKind.RETRAIN,
            task_slug=task_slug,
            task_workspace_root=task_workspace_root,
            parent_run_id=parent_run.id,
        ),
    )

    try:
        task = retrain_training.enqueue_retraining(
            pipeline=pipeline,
            user_id=user_id,
            run_id=run.id,
            task_slug=task_slug,
            task_workspace_root=task_workspace_root,
            parent_run=parent_run,
        )
    except Exception:
        # Retrain failures don't fail the pipeline — champion keeps serving.
        # Just mark the run failed so the durable record reflects the attempt.
        logic.mark_run_failed(run=run, failure_reason="task_create_failed")
        raise

    run.task_id = task.id
    run.save(update_fields=["task_id", "updated_at"])

    # Refresh and return the DTO (the manual run-row mutation above doesn't
    # round-trip through the facade's DTO conversion otherwise).
    refreshed = logic.get_pipeline_run(team_id=team_id, run_id=run.id)
    assert refreshed is not None
    return _run_to_dto(refreshed)


def pause(*, team_id: int, pipeline_id: UUID) -> contracts.AutoMLPipelineDTO:
    """Pause scheduled inference / training. Raises if transition isn't allowed."""
    obj = logic.transition_pipeline(team_id=team_id, pipeline_id=pipeline_id, new_status=PipelineStatus.PAUSED)
    return _to_dto(obj)


def resume(*, team_id: int, pipeline_id: UUID) -> contracts.AutoMLPipelineDTO:
    """Resume a paused pipeline. Raises if transition isn't allowed."""
    obj = logic.transition_pipeline(team_id=team_id, pipeline_id=pipeline_id, new_status=PipelineStatus.ACTIVE)
    return _to_dto(obj)


def archive(*, team_id: int, pipeline_id: UUID) -> contracts.AutoMLPipelineDTO:
    """Soft-delete a pipeline by transitioning to ``ARCHIVED``. Raises if not found or already archived."""
    obj = logic.transition_pipeline(team_id=team_id, pipeline_id=pipeline_id, new_status=PipelineStatus.ARCHIVED)
    return _to_dto(obj)


def record_training_result(
    *,
    team_id: int,
    pipeline_id: UUID,
    params: contracts.RecordTrainingResultInput,
    run_id: UUID | None = None,
) -> contracts.AutoMLModelVersionDTO:
    """Persist a completed training run as an ``AutoMLModelVersion``.

    Called by the orchestration agent (or a future Temporal activity) when
    a training run finishes. Default role is challenger — promotion to
    champion is a separate explicit step. Raises ``PipelineNotFoundError``
    if the pipeline doesn't exist on the team.

    When ``run_id`` is provided, the matching ``AutoMLPipelineRun`` is
    linked to the new version in the same transaction — its
    ``created_model_version_id`` is set and a compact training summary
    is denormalized onto its ``training_result``. Raises
    ``PipelineRunNotFoundError`` if the run id doesn't resolve.
    """
    obj = logic.record_training_result(team_id=team_id, pipeline_id=pipeline_id, params=params, run_id=run_id)
    return _version_to_dto(obj)


def list_model_versions(
    *,
    team_id: int,
    pipeline_id: UUID,
) -> list[contracts.AutoMLModelVersionDTO]:
    """List every model version for a pipeline, newest first.

    Archived versions are included — they're part of the audit trail and the
    ``$model_version_id`` on past predictions still needs to resolve.
    """
    return [_version_to_dto(obj) for obj in logic.list_model_versions(team_id=team_id, pipeline_id=pipeline_id)]


def get_active_model(
    *,
    team_id: int,
    pipeline_id: UUID,
    role: ModelRole,
) -> contracts.AutoMLModelVersionDTO | None:
    """Fetch the version currently holding a role on a pipeline.

    Returns ``None`` when no version holds that role. The partial unique
    constraint guarantees at most one champion and one challenger per
    pipeline.
    """
    obj = logic.get_active_model(team_id=team_id, pipeline_id=pipeline_id, role=role)
    return _version_to_dto(obj) if obj else None


def promote_to_champion(
    *,
    team_id: int,
    model_version_id: UUID,
) -> contracts.AutoMLModelVersionDTO:
    """Make ``model_version_id`` the champion for its pipeline.

    Atomic two-step: the existing champion (if any and different) is archived
    in the same transaction the target version is set to champion. No-op if
    the target is already the champion. Raises
    ``ModelVersionNotFoundError`` if the version doesn't belong to the team.
    """
    obj = logic.promote_to_champion(team_id=team_id, model_version_id=model_version_id)
    return _version_to_dto(obj)


def validate(
    *,
    team_id: int,
    params: contracts.CreatePipelineInput,
) -> contracts.ValidationReport:
    """Run preflight validation against a proposed pipeline config.

    Side-effect-free: nothing is written, no pipeline is created. Same body shape
    as ``create``; call this first so the user can see the validation report
    (volume, base rate, leakage warnings, sample plan) before committing to a
    pipeline. Returns a ``ValidationReport`` with findings tagged
    info/warn/block plus a summary of estimated sizes.

    Findings include both structural checks (config-shape, cadence ordering,
    naming) and data-touching checks (HogQL count queries for training /
    inference population size and the classification positive base rate). Data
    queries fail open — exceptions become ``info`` findings rather than blocking
    validation, so the caller always gets a structured response.
    """
    return logic.run_validation(team_id=team_id, params=params)


def list_runs_for_pipeline(
    *,
    team_id: int,
    pipeline_id: UUID,
) -> list[contracts.AutoMLPipelineRunDTO]:
    """List every run (bootstrap / retrain / inference) for a pipeline, newest first.

    Includes terminal runs (succeeded / failed / aborted) — the pipeline-detail
    timeline surfaces the full history. Use ``get_run`` to fetch one by id when
    the agent wants to look up its own run mid-flight.
    """
    return [_run_to_dto(obj) for obj in logic.list_pipeline_runs(team_id=team_id, pipeline_id=pipeline_id)]


def get_run(*, team_id: int, run_id: UUID) -> contracts.AutoMLPipelineRunDTO | None:
    """Fetch one pipeline run by id, scoped to the team. Returns ``None`` when not found."""
    obj = logic.get_pipeline_run(team_id=team_id, run_id=run_id)
    return _run_to_dto(obj) if obj else None


def record_eda_result(
    *,
    team_id: int,
    run_id: UUID,
    params: contracts.RecordEdaResultInput,
) -> contracts.AutoMLPipelineRunDTO:
    """Stash the agent's EDA output on an in-progress run.

    Called between `automl eda` and `automl train` (step 3 → step 4 of the
    CLI flow). Raises ``PipelineRunNotFoundError`` if the run doesn't exist
    on the team.
    """
    obj = logic.record_eda_result(team_id=team_id, run_id=run_id, params=params)
    return _run_to_dto(obj)


def record_bootstrap_outcome(
    *,
    team_id: int,
    run_id: UUID,
    params: contracts.RecordBootstrapOutcomeInput,
) -> contracts.AutoMLPipelineRunDTO:
    """Flip a run to a terminal state and write the agent's final outcome report.

    Single-shot — once a run reaches a terminal state, re-calling this
    no-ops (returns the already-terminal DTO). Lets the agent retry the
    MCP call after a transient network blip without overwriting the
    timeline. Raises ``ValueError`` if ``params.status`` is ``RUNNING``
    (terminal status required) and ``PipelineRunNotFoundError`` if the
    run doesn't exist on the team.
    """
    obj = logic.record_bootstrap_outcome(team_id=team_id, run_id=run_id, params=params)
    return _run_to_dto(obj)
