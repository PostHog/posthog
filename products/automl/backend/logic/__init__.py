"""Business logic for AutoML.

Validation, queries, and orchestration helpers live here.
The facade is a thin layer that calls into this module and
converts ORM models to frozen dataclasses.
"""

from __future__ import annotations

from uuid import UUID

from ..facade import contracts
from ..facade.enums import PipelineStatus
from ..models import AutoMLPipeline


def create_pipeline(params: contracts.CreatePipelineInput) -> AutoMLPipeline:
    """Persist a new pipeline in draft state.

    Validation lives here, not on the facade. Population / config validation
    against schema, MCP-style ``automl-validate`` checks (volume, base rate,
    leakage), and any sanity gating will be added incrementally.
    """
    return AutoMLPipeline.objects.create(
        team_id=params.team_id,
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
        created_by_id=params.created_by_id,
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
