"""Business logic for AutoML.

Validation, queries, and state transitions live here.
The facade is a thin layer that calls into this module and
converts ORM models to frozen dataclasses.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ..facade import contracts
from ..facade.enums import PipelineStatus
from ..models import AutoMLPipeline
from .validation import run_validation

__all__ = [
    "create_pipeline",
    "list_pipelines",
    "get_pipeline",
    "update_pipeline",
    "transition_pipeline",
    "set_runtime",
    "run_validation",
]

# Allowed status transitions: source -> set of allowed destinations.
# Lifecycle helpers below funnel writes through this map so the state
# machine stays explicit.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    PipelineStatus.DRAFT.value: {PipelineStatus.BOOTSTRAP_PENDING.value, PipelineStatus.ARCHIVED.value},
    PipelineStatus.BOOTSTRAP_PENDING.value: {
        PipelineStatus.BOOTSTRAP_RUNNING.value,
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

    `runtime` is system-managed (bootstrap_task_id, mlflow_run_id, last_inference_at,
    bootstrap_error, ...). User-configured intent lives in `config` — never touch
    that from runtime paths.
    """
    pipeline.runtime = {**pipeline.runtime, **updates}
    pipeline.save(update_fields=["runtime", "updated_at"])
    return pipeline
