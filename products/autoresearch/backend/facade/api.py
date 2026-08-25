"""
Public facade for autoresearch.

Every consumer — this product's own presentation layer included — reaches autoresearch
data and behavior through this module. Functions take and return the frozen contracts in
``contracts.py``; ORM rows never leave.

Scope is set at the entry boundary, so every read and write here takes ``team_id`` and
filters on it. Business rules live in the modules behind this facade, not in the views.
"""

import json
import base64
import hashlib
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone as django_timezone

from posthog.models.team import Team

from products.actions.backend.models.action import Action
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.sandbox import get_sandbox_class

from ..dataset import templates as templates_module
from ..dataset.labeling import POPULATION_KINDS as _POPULATION_KINDS
from ..dataset.validation import validate_pipeline_definition as _validate_pipeline_definition
from ..evaluation.online_validation import run_online_validation_for_pipeline
from ..inference.sandbox import SandboxInferenceError, features_parquet, labels_parquet, materialize_training_data
from ..inference.scoring import run_inference_for_pipeline
from ..models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchRun,
    AutoresearchSuggestion,
    AutoresearchTrainingRun,
)
from ..training import artifacts as artifact_store
from ..training.promotion import PromotionError, complete_training_run
from ..training.recipe_validation import RecipeValidationError, validate_feature_sql, validate_recipe
from ..training.runner import run_training
from .contracts import (
    ArtifactContent,
    ArtifactDeleteResult,
    ArtifactList,
    ArtifactNotFound,
    AutoresearchConflict,
    InvalidArtifactPath as InvalidArtifactPath,
    Iteration,
    IterationTrailEntry,
    MaterializedFeatures,
    Model,
    Pipeline,
    PipelineNotFound,
    PipelineValidation,
    PipelineWrite,
    ResolvedTemplate,
    Run,
    StoredArtifact,
    Suggestion,
    SuggestionNotFound as SuggestionNotFound,
    TemplateInfo,
    TrainingRun,
    TrainingRunHistory,
    TrainingRunHistoryEntry,
    TrainingRunNotFound,
    ValidationWarning,
)

# Where materialized training parquet lands inside the agent's sandbox. The agent reads
# these paths with pd.read_parquet — the rows never transit the model's context.
_AGENT_FEATURE_DIR = "/tmp/workspace/autoresearch/data"

_HISTORY_LIMIT_MAX = 20


# ── Mappers ────────────────────────────────────────────────────────────────


def _pipeline_to_contract(
    row: AutoresearchPipeline,
    *,
    champion_holdout_auc: float | None = None,
    champion_realized_auc: float | None = None,
) -> Pipeline:
    return Pipeline(
        id=row.id,
        name=row.name,
        description=row.description,
        target_event=row.target_event,
        target_definition=row.target_definition or {},
        horizon_days=row.horizon_days,
        training_lookback_days=row.training_lookback_days,
        training_population=row.training_population or {},
        inference_population=row.inference_population or {},
        cadence_days=row.cadence_days,
        iteration_budget=row.iteration_budget,
        iteration_budget_remaining=row.iteration_budget_remaining,
        success_auc=row.success_auc,
        plateau_iterations=row.plateau_iterations,
        output_person_property=row.output_person_property,
        status=row.status,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_scored_at=row.last_scored_at,
        champion_holdout_auc=champion_holdout_auc,
        champion_realized_auc=champion_realized_auc,
    )


def _pipeline_with_champion(row: AutoresearchPipeline) -> Pipeline:
    champion = row.models.filter(role=AutoresearchModel.Role.CHAMPION).order_by("-created_at").first()
    return _pipeline_to_contract(
        row,
        champion_holdout_auc=champion.holdout_score if champion else None,
        champion_realized_auc=champion.realized_score if champion else None,
    )


def _model_to_contract(row: AutoresearchModel) -> Model:
    return Model(
        id=row.id,
        pipeline=row.pipeline_id,
        role=row.role,
        recipe_hash=row.recipe_hash,
        model_recipe=row.model_recipe or {},
        model_explanation=row.model_explanation or {},
        holdout_score=row.holdout_score,
        realized_score=row.realized_score,
        calibration_error=row.calibration_error,
        metrics=row.metrics or {},
        source_training_run=row.source_training_run_id,
        agent_description=row.agent_description,
        trained_on_start=row.trained_on_start,
        trained_on_end=row.trained_on_end,
        is_preliminary=row.is_preliminary,
        promoted_at=row.promoted_at,
        archived_at=row.archived_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _iteration_trail_entry(row: AutoresearchIteration) -> IterationTrailEntry:
    return IterationTrailEntry(
        iteration_number=row.iteration_number,
        status=row.status,
        holdout_score=row.holdout_score,
        train_score=row.train_score,
        agent_description=row.agent_description,
        model_spec=row.model_spec or {},
    )


def _training_run_to_contract(row: AutoresearchTrainingRun) -> TrainingRun:
    return TrainingRun(
        id=row.id,
        pipeline=row.pipeline_id,
        task_id=row.task_id,
        task_run_id=row.task_run_id,
        task_url=f"/tasks/{row.task_id}" if row.task_id else None,
        status=row.status,
        iteration_budget=row.iteration_budget,
        iteration_count=row.iteration_count,
        best_holdout_score=row.best_holdout_score,
        summary=row.summary or None,
        iterations=[_iteration_trail_entry(i) for i in row.iterations.all()],
        error=row.error,
        started_at=row.started_at,
        completed_at=row.completed_at,
        created_at=row.created_at,
    )


def _iteration_to_contract(row: AutoresearchIteration) -> Iteration:
    return Iteration(
        id=row.id,
        pipeline=row.pipeline_id,
        training_run=row.training_run_id,
        iteration_number=row.iteration_number,
        recipe_hash=row.recipe_hash,
        recipe_snapshot=row.recipe_snapshot or {},
        model_spec=row.model_spec or {},
        train_score=row.train_score,
        holdout_score=row.holdout_score,
        status=row.status,
        agent_description=row.agent_description,
        agent_confidence=row.agent_confidence,
        parent_suggestion=row.parent_suggestion_id,
        created_at=row.created_at,
    )


def _suggestion_to_contract(row: AutoresearchSuggestion) -> Suggestion:
    return Suggestion(
        id=row.id,
        pipeline=row.pipeline_id,
        prompt=row.prompt,
        priority=row.priority,
        status=row.status,
        source=row.source,
        agent_response=row.agent_response,
        created_by=row.created_by,
        linked_iteration_ids=list(row.iterations.values_list("id", flat=True)),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _run_to_contract(row: AutoresearchRun) -> Run:
    return Run(
        id=row.id,
        pipeline=row.pipeline_id,
        model=row.model_id,
        run_type=row.run_type,
        status=row.status,
        rows_scored=row.rows_scored,
        metrics=row.metrics or {},
        error=row.error,
        started_at=row.started_at,
        completed_at=row.completed_at,
        created_at=row.created_at,
    )


# ── Row lookups (internal) ─────────────────────────────────────────────────


def _pipeline_row(team_id: int, pipeline_id: str | UUID) -> AutoresearchPipeline:
    try:
        return AutoresearchPipeline.objects.for_team(team_id).get(pk=str(pipeline_id))
    except (AutoresearchPipeline.DoesNotExist, ValueError, TypeError):
        raise PipelineNotFound("Pipeline not found.")


def _training_run_row(team_id: int, training_run_id: str | UUID) -> AutoresearchTrainingRun:
    try:
        return (
            AutoresearchTrainingRun.objects.for_team(team_id)
            .select_related("pipeline")
            .prefetch_related("iterations")
            .get(pk=str(training_run_id))
        )
    except (AutoresearchTrainingRun.DoesNotExist, ValueError, TypeError):
        raise TrainingRunNotFound("Training run not found.")


# ── Pipelines ──────────────────────────────────────────────────────────────


def list_pipelines(team_id: int, *, offset: int, limit: int) -> tuple[list[Pipeline], int]:
    """One page of the team's non-archived pipelines, newest first, plus the total count."""
    qs = (
        AutoresearchPipeline.objects.for_team(team_id)
        .exclude(status=AutoresearchPipeline.Status.ARCHIVED)
        .select_related("created_by")
        .order_by("-created_at")
    )
    count = qs.count()
    return [_pipeline_with_champion(row) for row in qs[offset : offset + limit]], count


def get_pipeline(team_id: int, pipeline_id: str | UUID) -> Pipeline:
    return _pipeline_with_champion(_pipeline_row(team_id, pipeline_id))


def create_pipeline(team_id: int, *, fields: dict[str, Any], created_by: Any) -> Pipeline:
    row = AutoresearchPipeline.objects.create(
        team_id=team_id,
        created_by=created_by,
        iteration_budget_remaining=fields.get("iteration_budget", 50),
        **fields,
    )
    return _pipeline_with_champion(row)


def update_pipeline(team_id: int, pipeline_id: str | UUID, *, fields: dict[str, Any]) -> Pipeline:
    row = _pipeline_row(team_id, pipeline_id)
    for key, value in fields.items():
        setattr(row, key, value)
    row.save()
    return _pipeline_with_champion(row)


def delete_pipeline(team_id: int, pipeline_id: str | UUID) -> None:
    _pipeline_row(team_id, pipeline_id).delete()


def set_pipeline_status(team_id: int, pipeline_id: str | UUID, *, status: str) -> Pipeline:
    """Archive, pause, or resume a pipeline.

    Resuming refuses anything that is not paused, so a caller cannot use it to revive an
    archived pipeline or restart a converged one.
    """
    row = _pipeline_row(team_id, pipeline_id)
    if status == AutoresearchPipeline.Status.RUNNING and row.status != AutoresearchPipeline.Status.PAUSED:
        raise AutoresearchConflict("Pipeline is not paused.")
    row.status = status
    row.save(update_fields=["status", "updated_at"])
    return _pipeline_with_champion(row)


def pipeline_has_models(team_id: int, pipeline_id: str | UUID) -> bool:
    """Whether any model has been trained for this pipeline yet.

    The model-defining fields freeze once this is true — scoring keeps loading the trained
    artifact, so changing them would silently answer a different question.
    """
    return _pipeline_row(team_id, pipeline_id).models.exists()


def get_pipeline_definition(team_id: int, pipeline_id: str | UUID) -> PipelineWrite:
    """The stored values of the fields a write body can carry, for change detection."""
    row = _pipeline_row(team_id, pipeline_id)
    return PipelineWrite(
        name=row.name,
        description=row.description,
        target_event=row.target_event,
        target_definition=row.target_definition or {},
        horizon_days=row.horizon_days,
        training_lookback_days=row.training_lookback_days,
        training_population=row.training_population or {},
        inference_population=row.inference_population or {},
        cadence_days=row.cadence_days,
        iteration_budget=row.iteration_budget,
        success_auc=row.success_auc,
        plateau_iterations=row.plateau_iterations,
        output_person_property=row.output_person_property,
    )


def output_person_property_taken(team_id: int, value: str, *, exclude_pipeline_id: str | UUID | None = None) -> bool:
    """Whether a live pipeline on this team already writes to that person property.

    Two pipelines writing the same property would clobber each other's scores.
    """
    qs = AutoresearchPipeline.objects.for_team(team_id).filter(output_person_property=value)
    qs = qs.exclude(status=AutoresearchPipeline.Status.ARCHIVED)
    if exclude_pipeline_id is not None:
        qs = qs.exclude(pk=str(exclude_pipeline_id))
    return qs.exists()


def resolve_action_target(team_id: int, action_id: Any) -> tuple[str, int]:
    """Resolve an action target to ``(action_name, action_id)``, scoped to the team.

    Raises ``PipelineNotFound`` when the action is missing or belongs to another project,
    so a foreign action id cannot be probed through this endpoint.
    """
    try:
        action = Action.objects.get(id=action_id, team_id=team_id)
    except (Action.DoesNotExist, ValueError, TypeError):
        raise PipelineNotFound(f"Action {action_id} was not found in this project.")
    return action.name or "", int(action_id)


# ── Validation and templates ───────────────────────────────────────────────


def list_templates() -> list[TemplateInfo]:
    return [
        TemplateInfo(
            key=t.key,
            display_name=t.display_name,
            description=t.description,
            default_horizon_days=t.default_horizon_days,
            requires_user_event=t.requires_user_event,
            requires_activity_resolution=t.requires_activity_resolution,
            notes=t.notes,
        )
        for t in templates_module.TEMPLATES.values()
    ]


def resolve_template(
    team_id: int,
    *,
    template_key: str,
    target_event_override: str | None = None,
    horizon_days_override: int | None = None,
) -> ResolvedTemplate:
    team = Team.objects.get(pk=team_id)
    try:
        resolved = templates_module.resolve_template(
            team=team,
            template_key=template_key,
            target_event_override=target_event_override,
            horizon_days_override=horizon_days_override,
        )
    except ValueError as exc:
        raise AutoresearchConflict(str(exc)) from exc
    return ResolvedTemplate(
        template_key=resolved.template_key,
        display_name=resolved.display_name,
        description=resolved.description,
        suggested_name=resolved.suggested_name,
        target_event=resolved.target_event,
        resolved_activity_event=resolved.resolved_activity_event,
        activity_event_alternatives=list(resolved.activity_event_alternatives),
        horizon_days=resolved.horizon_days,
        training_population=resolved.training_population,
        inference_population=resolved.inference_population,
        output_person_property=resolved.output_person_property,
        notes=resolved.notes,
    )


def validate_definition(
    team_id: int,
    *,
    target_event: str,
    target_definition: dict[str, Any],
    horizon_days: int,
    training_lookback_days: int,
    training_population: dict[str, Any],
    inference_population: dict[str, Any],
) -> PipelineValidation:
    team = Team.objects.get(pk=team_id)
    result = _validate_pipeline_definition(
        team=team,
        target_event=target_event,
        target_definition=target_definition,
        horizon_days=horizon_days,
        training_lookback_days=training_lookback_days,
        training_population=training_population,
        inference_population=inference_population,
    )
    return PipelineValidation(
        can_proceed=result.can_proceed,
        requires_acknowledgement=result.requires_acknowledgement,
        estimated_training_rows=result.estimated_training_rows,
        positive_count=result.positive_count,
        negative_count=result.negative_count,
        base_rate=result.base_rate,
        inference_population_size=result.inference_population_size,
        warnings=[ValidationWarning(code=w.code, message=w.message, severity=w.severity) for w in result.warnings],
        error=result.error,
    )


def validate_features_sql(features_sql: str) -> None:
    """Raise ``AutoresearchConflict`` if the agent's feature SQL is not a safe read-only SELECT."""
    try:
        validate_feature_sql(features_sql)
    except RecipeValidationError as exc:
        raise AutoresearchConflict(str(exc)) from exc


# ── Models ─────────────────────────────────────────────────────────────────


def list_models(team_id: int, *, pipeline_id: str | UUID | None, offset: int, limit: int) -> tuple[list[Model], int]:
    qs = AutoresearchModel.objects.for_team(team_id).select_related("pipeline").order_by("-created_at")
    if pipeline_id:
        qs = qs.filter(pipeline_id=str(pipeline_id))
    count = qs.count()
    return [_model_to_contract(row) for row in qs[offset : offset + limit]], count


def get_model(team_id: int, model_id: str | UUID) -> Model | None:
    row = AutoresearchModel.objects.for_team(team_id).filter(pk=str(model_id)).first()
    return _model_to_contract(row) if row else None


# ── Operational runs ───────────────────────────────────────────────────────


def list_runs(team_id: int, *, pipeline_id: str | UUID | None, offset: int, limit: int) -> tuple[list[Run], int]:
    qs = AutoresearchRun.objects.for_team(team_id).select_related("pipeline", "model").order_by("-created_at")
    if pipeline_id:
        qs = qs.filter(pipeline_id=str(pipeline_id))
    count = qs.count()
    return [_run_to_contract(row) for row in qs[offset : offset + limit]], count


def get_run(team_id: int, run_id: str | UUID) -> Run | None:
    row = AutoresearchRun.objects.for_team(team_id).filter(pk=str(run_id)).first()
    return _run_to_contract(row) if row else None


def score_pipeline(team_id: int, pipeline_id: str | UUID) -> Run:
    """Score the inference population with the champion model and emit prediction events."""
    pipeline = _pipeline_row(team_id, pipeline_id)
    if pipeline.status == AutoresearchPipeline.Status.ARCHIVED:
        raise AutoresearchConflict("Cannot score an archived pipeline.")
    champion = (
        AutoresearchModel.objects.for_team(team_id)
        .filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
        .order_by("-created_at")
        .first()
    )
    if not champion:
        raise AutoresearchConflict("No champion model found. Run training first.")
    return _run_to_contract(run_inference_for_pipeline(pipeline=pipeline, model=champion))


def validate_pipeline_online(team_id: int, pipeline_id: str | UUID) -> list[Run]:
    """Score matured prediction dates against realized outcomes."""
    pipeline = _pipeline_row(team_id, pipeline_id)
    if pipeline.status == AutoresearchPipeline.Status.ARCHIVED:
        raise AutoresearchConflict("Cannot validate an archived pipeline.")
    return [_run_to_contract(run) for run in run_online_validation_for_pipeline(pipeline=pipeline)]


# ── Training runs ──────────────────────────────────────────────────────────


def list_training_runs(
    team_id: int, *, pipeline_id: str | UUID | None, offset: int, limit: int
) -> tuple[list[TrainingRun], int]:
    qs = (
        AutoresearchTrainingRun.objects.for_team(team_id)
        .select_related("pipeline")
        .prefetch_related("iterations")
        .order_by("-created_at")
    )
    if pipeline_id:
        qs = qs.filter(pipeline_id=str(pipeline_id))
    count = qs.count()
    return [_training_run_to_contract(row) for row in qs[offset : offset + limit]], count


def get_training_run(team_id: int, training_run_id: str | UUID) -> TrainingRun | None:
    try:
        return _training_run_to_contract(_training_run_row(team_id, training_run_id))
    except TrainingRunNotFound:
        return None


def start_training(team_id: int, pipeline_id: str | UUID, *, iteration_budget: int | None, user_id: int) -> TrainingRun:
    """Start an asynchronous training run in a sandbox.

    Mirrors the scheduled coordinator's kickoff guard: the pipeline row is locked so a
    concurrent manual and scheduled start serialize, and a second live run is refused.
    ``run_training`` stays inside the lock so the new run row commits before a waiting
    request re-checks.
    """
    with transaction.atomic():
        pipeline = AutoresearchPipeline.objects.for_team(team_id).select_for_update().get(pk=str(pipeline_id))
        if pipeline.status == AutoresearchPipeline.Status.ARCHIVED:
            raise AutoresearchConflict("Cannot start training on an archived pipeline.")
        if (
            AutoresearchTrainingRun.objects.for_team(team_id)
            .filter(pipeline=pipeline, status=AutoresearchTrainingRun.Status.RUNNING)
            .exists()
        ):
            raise AutoresearchConflict(
                "A training run is already in progress for this pipeline. "
                "Wait for it to finish, or check its status in the training runs list."
            )
        budget = iteration_budget or pipeline.iteration_budget
        training_run = run_training(pipeline=pipeline, iteration_budget=budget, user_id=user_id)
    return _training_run_to_contract(training_run)


def open_training_run(team_id: int, pipeline_id: str | UUID, *, iteration_budget: int | None) -> TrainingRun:
    """Open a run an external agent will record iterations against."""
    pipeline = _pipeline_row(team_id, pipeline_id)
    if pipeline.status == AutoresearchPipeline.Status.ARCHIVED:
        raise AutoresearchConflict("Cannot open a training run on an archived pipeline.")
    row = AutoresearchTrainingRun.objects.create(
        pipeline=pipeline,
        status=AutoresearchTrainingRun.Status.RUNNING,
        iteration_budget=iteration_budget or pipeline.iteration_budget,
        started_at=django_timezone.now(),
    )
    return _training_run_to_contract(row)


def record_iteration(team_id: int, training_run_id: str | UUID, *, fields: dict[str, Any]) -> Iteration:
    """Record one iteration of an open run. Idempotent on ``iteration_number``."""
    training_run = _training_run_row(team_id, training_run_id)
    if training_run.status != AutoresearchTrainingRun.Status.RUNNING:
        raise AutoresearchConflict("Can only record iterations on a running training run.")

    recipe_snapshot = fields["recipe_snapshot"]
    model_spec = fields["model_spec"]
    recipe_hash = hashlib.sha256(
        json.dumps({"recipe": recipe_snapshot, "spec": model_spec}, sort_keys=True).encode()
    ).hexdigest()

    # Scope the suggestion lookup to this run's pipeline so a foreign suggestion id
    # cannot be attached across tenants.
    parent_suggestion = None
    parent_suggestion_id = fields.get("parent_suggestion")
    if parent_suggestion_id:
        parent_suggestion = (
            AutoresearchSuggestion.objects.for_team(team_id)
            .filter(id=parent_suggestion_id, pipeline=training_run.pipeline)
            .first()
        )
        if parent_suggestion is None:
            raise AutoresearchConflict("parent_suggestion not found on this pipeline.")

    iteration, _ = AutoresearchIteration.objects.update_or_create(
        training_run=training_run,
        iteration_number=fields["iteration_number"],
        defaults={
            "pipeline": training_run.pipeline,
            "recipe_hash": recipe_hash,
            "recipe_snapshot": recipe_snapshot,
            "model_spec": model_spec,
            "train_score": fields.get("train_score"),
            "holdout_score": fields.get("holdout_score"),
            "status": fields["status"],
            "agent_description": fields.get("agent_description", ""),
            "agent_confidence": fields.get("agent_confidence"),
            "parent_suggestion": parent_suggestion,
        },
    )

    # Spawning an iteration from a suggestion is itself acting on it — advance the suggestion so
    # the UI reflects the pickup even if the agent never calls the respond endpoint.
    if parent_suggestion and parent_suggestion.status in (
        AutoresearchSuggestion.Status.QUEUED,
        AutoresearchSuggestion.Status.PICKED_UP,
    ):
        parent_suggestion.status = AutoresearchSuggestion.Status.ACTED_ON
        parent_suggestion.save(update_fields=["status", "updated_at"])

    return _iteration_to_contract(iteration)


def complete_run(
    team_id: int,
    training_run_id: str | UUID,
    *,
    best_iteration_id: Any = None,
    model_explanation: dict[str, Any] | None = None,
    recommended_next: str = "",
    distillation: str = "",
) -> TrainingRun:
    """Finalize a run. Promotion is server-side — an agent cannot set the champion."""
    training_run = _training_run_row(team_id, training_run_id)
    if training_run.status not in (
        AutoresearchTrainingRun.Status.RUNNING,
        AutoresearchTrainingRun.Status.PENDING,
    ):
        raise AutoresearchConflict("Training run is already completed or failed.")
    try:
        complete_training_run(
            training_run,
            best_iteration_id=best_iteration_id,
            model_explanation=model_explanation or {},
            recommended_next=recommended_next or "",
            distillation=distillation or "",
        )
    except PromotionError as exc:
        raise AutoresearchConflict(str(exc)) from exc
    training_run.refresh_from_db()
    return _training_run_to_contract(training_run)


def training_run_history(team_id: int, pipeline_id: str | UUID, *, limit: int = 5) -> TrainingRunHistory:
    """Prior completed runs a new run reads to orient.

    This pipeline's own history first, backfilled with same-target sibling pipelines on the
    team, so a fresh pipeline still inherits what the team already learned about the target.
    """
    pipeline = _pipeline_row(team_id, pipeline_id)
    limit = max(1, min(limit, _HISTORY_LIMIT_MAX))

    completed = (
        AutoresearchTrainingRun.objects.for_team(team_id)
        .filter(status=AutoresearchTrainingRun.Status.COMPLETED)
        .select_related("pipeline")
        .prefetch_related("iterations")
    )
    runs = list(completed.filter(pipeline=pipeline).order_by("-completed_at")[:limit])
    remaining = limit - len(runs)
    if remaining > 0:
        runs += list(
            completed.filter(pipeline__target_event=pipeline.target_event)
            .exclude(pipeline=pipeline)
            .order_by("-completed_at")[:remaining]
        )

    return TrainingRunHistory(
        runs=[
            TrainingRunHistoryEntry(
                run_id=run.id,
                pipeline_id=run.pipeline_id,
                is_current_pipeline=run.pipeline_id == pipeline.id,
                target_event=run.pipeline.target_event,
                horizon_days=run.pipeline.horizon_days,
                best_holdout_score=run.best_holdout_score,
                iteration_count=run.iteration_count,
                completed_at=run.completed_at,
                summary=run.summary or None,
                iterations=[_iteration_trail_entry(i) for i in run.iterations.all()],
            )
            for run in runs
        ]
    )


# ── Feature materialization ────────────────────────────────────────────────


def materialize_features(team_id: int, training_run_id: str | UUID, *, features_sql: str) -> MaterializedFeatures:
    """Run ``features_sql`` server-side and write the parquet into this run's sandbox.

    The rows never pass through the agent's context and there is no row cap. The destination
    paths are fixed by the framework — the agent supplies the query, never where it lands.
    """
    training_run = _training_run_row(team_id, training_run_id)
    if training_run.status != AutoresearchTrainingRun.Status.RUNNING:
        raise AutoresearchConflict("Can only materialize features for a running training run.")
    validate_features_sql(features_sql)

    sandbox_id = _resolve_run_sandbox_id(training_run)
    team = Team.objects.get(pk=team_id)
    try:
        data = materialize_training_data(team=team, pipeline=training_run.pipeline, feature_sql=features_sql)
    except (SandboxInferenceError, RecipeValidationError) as exc:
        raise AutoresearchConflict(f"Feature materialization failed: {exc}") from exc
    if not data.train_rows:
        raise AutoresearchConflict("features_sql produced no training rows.")
    if not data.feature_cols:
        raise AutoresearchConflict("features_sql produced no numeric feature columns.")

    paths = _write_feature_parquets(sandbox_id, data)
    return MaterializedFeatures(
        train_features_path=paths["train_features_path"],
        train_labels_path=paths["train_labels_path"],
        holdout_features_path=paths["holdout_features_path"],
        holdout_labels_path=paths["holdout_labels_path"],
        n_train=len(data.train_rows),
        n_holdout=len(data.holdout_rows),
        n_features=len(data.feature_cols),
        feature_cols=list(data.feature_cols),
    )


def _resolve_run_sandbox_id(training_run: AutoresearchTrainingRun) -> str:
    """Resolve the live sandbox for this run from its TaskRun state.

    The sandbox id comes from the team-scoped run record, never from the client, and is
    verified to belong to this training run.
    """
    if not training_run.task_run_id:
        raise AutoresearchConflict("This training run has no sandbox (e.g. a stub run). Cannot materialize features.")
    task_run = tasks_facade.get_task_run(training_run.task_run_id)
    if task_run is None:
        raise AutoresearchConflict("Sandbox task run not found for this training run.")
    state = task_run.state or {}
    if str(state.get("autoresearch_training_run_id")) != str(training_run.id):
        raise AutoresearchConflict("Sandbox does not belong to this training run.")
    sandbox_id = state.get("sandbox_id")
    if not sandbox_id:
        raise AutoresearchConflict("Sandbox is not ready yet — try again once the agent has started.")
    return str(sandbox_id)


def _write_feature_parquets(sandbox_id: str, data: Any) -> dict[str, str]:
    """Serialize the train/holdout matrices to parquet and write them into the agent's sandbox."""
    try:
        sandbox = get_sandbox_class().get_by_id(sandbox_id)
    except Exception as exc:
        raise AutoresearchConflict(f"Could not connect to the run's sandbox: {exc}") from exc
    files = {
        "train_features_path": (
            f"{_AGENT_FEATURE_DIR}/train_features.parquet",
            features_parquet(data.train_rows, data.feature_cols),
        ),
        "train_labels_path": (f"{_AGENT_FEATURE_DIR}/train_labels.parquet", labels_parquet(data.train_rows)),
        "holdout_features_path": (
            f"{_AGENT_FEATURE_DIR}/holdout_features.parquet",
            features_parquet(data.holdout_rows, data.feature_cols),
        ),
        "holdout_labels_path": (
            f"{_AGENT_FEATURE_DIR}/holdout_labels.parquet",
            labels_parquet(data.holdout_rows),
        ),
    }
    paths: dict[str, str] = {}
    for key, (path, content) in files.items():
        result = sandbox.write_file(path, content)
        if result.exit_code != 0:
            raise AutoresearchConflict(f"Failed to write {path} into the sandbox: {result.stderr[:300]}")
        paths[key] = path
    return paths


# ── Artifact bundle ────────────────────────────────────────────────────────


def _bundle_prefix(team_id: int, training_run: AutoresearchTrainingRun) -> str:
    return artifact_store.bundle_prefix(
        team_id=team_id,
        pipeline_id=str(training_run.pipeline_id),
        training_run_id=str(training_run.id),
    )


def list_artifacts(team_id: int, training_run_id: str | UUID) -> ArtifactList:
    training_run = _training_run_row(team_id, training_run_id)
    paths = artifact_store.list_artifacts(_bundle_prefix(team_id, training_run))
    return ArtifactList(paths=paths, count=len(paths))


def write_artifact(team_id: int, training_run_id: str | UUID, *, path: str, content_base64: str) -> StoredArtifact:
    """Store one file of the run's bundle. The bundle freezes once the run leaves ``running``."""
    training_run = _training_run_row(team_id, training_run_id)
    if training_run.status != AutoresearchTrainingRun.Status.RUNNING:
        raise AutoresearchConflict("Can only upload artifacts on a running training run.")
    try:
        content = base64.b64decode(content_base64, validate=True)
    except Exception as exc:
        raise AutoresearchConflict("content_base64 is not valid base64.") from exc
    try:
        stored = artifact_store.write_artifact(_bundle_prefix(team_id, training_run), path, content)
    except artifact_store.InvalidArtifactPath as exc:
        raise InvalidArtifactPath(str(exc)) from exc
    return StoredArtifact(path=stored.path, size_bytes=stored.size_bytes, sha256=stored.sha256)


def read_artifact(team_id: int, training_run_id: str | UUID, *, path: str) -> ArtifactContent:
    training_run = _training_run_row(team_id, training_run_id)
    prefix = _bundle_prefix(team_id, training_run)
    try:
        content = artifact_store.read_artifact(prefix, path)
    except artifact_store.InvalidArtifactPath as exc:
        raise InvalidArtifactPath(str(exc)) from exc
    except artifact_store.BundleNotFound as exc:
        raise ArtifactNotFound(str(exc)) from exc
    return ArtifactContent(
        path=artifact_store.normalize_artifact_path(path),
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        content_base64=base64.b64encode(content).decode("ascii"),
    )


def delete_artifact(team_id: int, training_run_id: str | UUID, *, path: str) -> ArtifactDeleteResult:
    training_run = _training_run_row(team_id, training_run_id)
    if training_run.status != AutoresearchTrainingRun.Status.RUNNING:
        raise AutoresearchConflict("Can only delete artifacts on a running training run.")
    try:
        deleted = artifact_store.delete_artifact(_bundle_prefix(team_id, training_run), path)
        normalized = artifact_store.normalize_artifact_path(path)
    except artifact_store.InvalidArtifactPath as exc:
        raise InvalidArtifactPath(str(exc)) from exc
    return ArtifactDeleteResult(path=normalized, deleted=deleted)


# ── Suggestions ────────────────────────────────────────────────────────────


def list_suggestions(
    team_id: int, *, pipeline_id: str | UUID | None, offset: int, limit: int
) -> tuple[list[Suggestion], int]:
    qs = (
        AutoresearchSuggestion.objects.for_team(team_id)
        .select_related("pipeline", "created_by")
        .order_by("-created_at")
    )
    if pipeline_id:
        qs = qs.filter(pipeline_id=str(pipeline_id))
    count = qs.count()
    return [_suggestion_to_contract(row) for row in qs[offset : offset + limit]], count


def get_suggestion(team_id: int, suggestion_id: str | UUID) -> Suggestion | None:
    row = AutoresearchSuggestion.objects.for_team(team_id).filter(pk=str(suggestion_id)).first()
    return _suggestion_to_contract(row) if row else None


def create_suggestion(
    team_id: int, pipeline_id: str | UUID, *, prompt: str, priority: str, created_by: Any
) -> Suggestion:
    pipeline = _pipeline_row(team_id, pipeline_id)
    if pipeline.status == AutoresearchPipeline.Status.ARCHIVED:
        raise AutoresearchConflict("Cannot submit suggestions to an archived pipeline.")
    row = AutoresearchSuggestion.objects.create(
        pipeline=pipeline,
        created_by=created_by,
        prompt=prompt,
        priority=priority,
        source=AutoresearchSuggestion.Source.USER,
    )
    return _suggestion_to_contract(row)


def respond_to_suggestion(
    team_id: int, suggestion_id: str | UUID, *, status: str, agent_response: str | None = None
) -> Suggestion:
    """Record how the agent handled a suggestion."""
    row = AutoresearchSuggestion.objects.for_team(team_id).filter(pk=str(suggestion_id)).first()
    if row is None:
        raise SuggestionNotFound("Suggestion not found.")
    row.status = status
    if agent_response:
        row.agent_response = agent_response
    row.save(update_fields=["status", "agent_response", "updated_at"])
    return _suggestion_to_contract(row)


# ── Recipe validation surface for the presentation layer ───────────────────

# The semantic population kinds the labeler can compile. Presentation validates a submitted
# spec against this so an uncompilable population is refused at creation, not at query time.
POPULATION_KINDS = _POPULATION_KINDS


def validate_iteration_recipe(*, model_spec: dict[str, Any], recipe_snapshot: dict[str, Any]) -> None:
    """Raise ``AutoresearchConflict`` if an agent-submitted recipe is outside the allowlist."""
    try:
        validate_recipe(model_spec=model_spec, recipe_snapshot=recipe_snapshot)
    except RecipeValidationError as exc:
        raise AutoresearchConflict(str(exc)) from exc


# ── Choice vocabularies for the presentation layer ─────────────────────────

# The (value, label) pairs behind each status-like field. Presentation declares its
# ChoiceFields from these so the generated enum components keep the names and labels the
# model-bound serializers produced — including the one shared with another product, which
# `ENUM_NAME_OVERRIDES` pins by value set.
PIPELINE_STATUS_CHOICES = AutoresearchPipeline.Status.choices
MODEL_ROLE_CHOICES = AutoresearchModel.Role.choices
TRAINING_RUN_STATUS_CHOICES = AutoresearchTrainingRun.Status.choices
ITERATION_STATUS_CHOICES = AutoresearchIteration.Status.choices
SUGGESTION_PRIORITY_CHOICES = AutoresearchSuggestion.Priority.choices
SUGGESTION_STATUS_CHOICES = AutoresearchSuggestion.Status.choices
SUGGESTION_SOURCE_CHOICES = AutoresearchSuggestion.Source.choices
RUN_TYPE_CHOICES = AutoresearchRun.RunType.choices
RUN_STATUS_CHOICES = AutoresearchRun.Status.choices
