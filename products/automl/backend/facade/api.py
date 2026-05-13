"""
Facade for AutoML.

The ONLY module other products are allowed to import. Accepts
frozen dataclasses, calls logic/, returns frozen dataclasses.
Never returns ORM instances or imports DRF.
"""

from __future__ import annotations

from uuid import UUID

from .. import logic
from ..models import AutoMLPipeline
from ..training import bootstrap
from . import contracts
from .enums import AutonomyLevel, Cadence, PipelineStatus, TaskType

# Re-export domain exceptions so callers don't have to dig into contracts.
PipelineNotFoundError = contracts.PipelineNotFoundError
PipelineStateTransitionError = contracts.PipelineStateTransitionError


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
