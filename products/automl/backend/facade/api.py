"""
Facade for AutoML.

The ONLY module other products are allowed to import. Accepts
frozen dataclasses, calls logic/, returns frozen dataclasses.
Never returns ORM instances or imports DRF.
"""

from __future__ import annotations

from uuid import UUID

from .. import logic
from ..models import AutoMLModelVersion, AutoMLPipeline
from ..training import bootstrap
from . import contracts
from .enums import AutonomyLevel, Cadence, ModelRole, PipelineStatus, TaskType

# Re-export domain exceptions so callers don't have to dig into contracts.
PipelineNotFoundError = contracts.PipelineNotFoundError
PipelineStateTransitionError = contracts.PipelineStateTransitionError
ModelVersionNotFoundError = contracts.ModelVersionNotFoundError


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

    Two-phase:
      1. State transition (DRAFT/FAILED -> BOOTSTRAP_PENDING). Fails fast on
         disallowed moves via ``PipelineStateTransitionError``.
      2. Enqueue a Task in the ``tasks`` product (single-shot agent run in a
         sandbox). On enqueue failure the pipeline is transitioned to FAILED
         with the error stashed in ``runtime.bootstrap_error`` so the user can
         see why and retry.

    The Task's id lands on the pipeline as ``runtime.bootstrap_task_id``.
    Returns the post-enqueue DTO.
    """
    obj = logic.transition_pipeline(
        team_id=team_id, pipeline_id=pipeline_id, new_status=PipelineStatus.BOOTSTRAP_PENDING
    )

    try:
        task = bootstrap.enqueue_bootstrap_training(pipeline=obj, user_id=user_id)
    except Exception as exc:
        # Surface the failure so the user can retry. Use str(exc) only — the
        # full traceback stays in logs, not in user-visible runtime state.
        logic.set_runtime(pipeline=obj, bootstrap_error=str(exc))
        logic.transition_pipeline(team_id=team_id, pipeline_id=pipeline_id, new_status=PipelineStatus.FAILED)
        raise

    obj = logic.set_runtime(pipeline=obj, bootstrap_task_id=str(task.id))
    return _to_dto(obj)


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
) -> contracts.AutoMLModelVersionDTO:
    """Persist a completed training run as an ``AutoMLModelVersion``.

    Called by the orchestration agent (or a future Temporal activity) when
    a training run finishes. Default role is challenger — promotion to
    champion is a separate explicit step. Raises ``PipelineNotFoundError``
    if the pipeline doesn't exist on the team.
    """
    obj = logic.record_training_result(team_id=team_id, pipeline_id=pipeline_id, params=params)
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
