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


def start(*, team_id: int, pipeline_id: UUID) -> contracts.AutoMLPipelineDTO:
    """Transition a draft pipeline into bootstrap-pending state.

    Raises ``PipelineNotFoundError`` or ``PipelineStateTransitionError``.
    The actual Temporal training workflow is wired in a follow-up commit.
    """
    obj = logic.transition_pipeline(
        team_id=team_id, pipeline_id=pipeline_id, new_status=PipelineStatus.BOOTSTRAP_PENDING
    )
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
