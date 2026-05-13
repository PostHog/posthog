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


def create(params: contracts.CreatePipelineInput) -> contracts.AutoMLPipelineDTO:
    obj = logic.create_pipeline(params)
    return _to_dto(obj)


def list_for_team(*, team_id: int) -> list[contracts.AutoMLPipelineDTO]:
    return [_to_dto(obj) for obj in logic.list_pipelines(team_id=team_id)]


def get(*, team_id: int, pipeline_id: UUID) -> contracts.AutoMLPipelineDTO | None:
    obj = logic.get_pipeline(team_id=team_id, pipeline_id=pipeline_id)
    return _to_dto(obj) if obj else None
