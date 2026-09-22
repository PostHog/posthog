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
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone as django_timezone

from posthog.models.team import Team
from posthog.models.user import User
from posthog.storage.object_storage import ObjectStorageError

from products.actions.backend.models.action import Action

from ..dataset import templates as templates_module
from ..dataset.labeling import (
    POPULATION_KINDS as _POPULATION_KINDS,
    PREDICTION_EVENT_NAME as _PREDICTION_EVENT_NAME,
)
from ..dataset.templates import TemplateKey as _TemplateKey
from ..dataset.validation import (
    ValidationWarningCode as _ValidationWarningCode,
    validate_pipeline_definition as _validate_pipeline_definition,
)
from ..models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchRun,
    AutoresearchSuggestion,
    AutoresearchTrainingRun,
)
from ..training import artifacts as artifact_store
from ..training.recipe_validation import RecipeValidationError, validate_feature_sql, validate_recipe
from .contracts import (
    ArtifactContent,
    ArtifactDeleteResult,
    ArtifactList,
    ArtifactNotFound,
    ArtifactStorageUnavailable,
    AutoresearchConflict,
    InvalidArtifactPath as InvalidArtifactPath,
    InvalidTarget,
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
    TemplateInfo,
    TrainingRun,
    TrainingRunHistory,
    TrainingRunHistoryEntry,
    TrainingRunNotFound,
    ValidationWarning,
)

AUTORESEARCH_FLAG = "autoresearch"


def flag_key() -> str:
    """The feature flag that gates every autoresearch surface."""
    return AUTORESEARCH_FLAG


# Where materialized training parquet lands inside the agent's sandbox. The agent reads
# these paths with pd.read_parquet — the rows never transit the model's context.
_AGENT_FEATURE_DIR = "/tmp/workspace/autoresearch/data"

# Every bundle file is capped at MAX_ARTIFACT_BYTES, so this also bounds the bundle's total size.
MAX_BUNDLE_FILES = 32

HISTORY_LIMIT_MAX = 20


def _as_uuid(value: str | UUID | None) -> UUID | None:
    """A pk from a URL as a UUID, or None when it cannot be one.

    An id that is not a UUID matches nothing, so callers filter it down to an empty result
    rather than letting the malformed value reach the database.
    """
    if value is None:
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


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
        # A row created outside the API keeps the column default ({}); it means the bare event
        # target, which is the shape the read schema declares.
        target_definition=row.target_definition or {"type": "event"},
        horizon_days=row.horizon_days,
        training_lookback_days=row.training_lookback_days,
        training_population=row.training_population or {},
        inference_population=row.inference_population or {},
        cadence_days=row.cadence_days,
        iteration_budget=row.iteration_budget,
        # The column is nullable (an admin can clear it); read that as no budget left
        # rather than widening the contract type.
        iteration_budget_remaining=row.iteration_budget_remaining or 0,
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
        recipe_snapshot=row.recipe_snapshot or {},
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


def _pipeline_row(team_id: int, pipeline_id: str | UUID, *, live_only: bool = False) -> AutoresearchPipeline:
    """One pipeline in this team.

    ``live_only`` excludes archived rows, which is what the pipeline's own detail routes do: an
    archived pipeline is gone as far as they are concerned, so acting on one is a 404 rather than
    a refusal that admits it exists. Routes nested under a pipeline id keep seeing archived rows,
    so they can explain why the write is refused.
    """
    pipeline_uuid = _as_uuid(pipeline_id)
    if pipeline_uuid is None:
        raise PipelineNotFound("Pipeline not found.")
    qs = AutoresearchPipeline.objects.for_team(team_id)
    if live_only:
        qs = qs.exclude(status=AutoresearchPipeline.Status.ARCHIVED)
    try:
        return qs.get(pk=pipeline_uuid)
    except AutoresearchPipeline.DoesNotExist:
        raise PipelineNotFound("Pipeline not found.")


def _training_run_row(
    team_id: int,
    training_run_id: str | UUID,
    *,
    pipeline_id: str | UUID | None = None,
    with_iterations: bool = True,
    for_update: bool = False,
) -> AutoresearchTrainingRun:
    """One training run in this team, and under ``pipeline_id`` when the route names one.

    ``for_update`` locks the run row only, not the joined pipeline row, which other claims lock.
    """
    training_run_uuid = _as_uuid(training_run_id)
    if training_run_uuid is None:
        raise TrainingRunNotFound("Training run not found.")
    qs = AutoresearchTrainingRun.objects.for_team(team_id).select_related("pipeline")
    if with_iterations:
        qs = qs.prefetch_related("iterations")
    if for_update:
        qs = qs.select_for_update(of=("self",))
    if pipeline_id:
        qs = qs.filter(pipeline_id=_as_uuid(pipeline_id))
    try:
        return qs.get(pk=training_run_uuid)
    except AutoresearchTrainingRun.DoesNotExist:
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
    return _pipeline_with_champion(_pipeline_row(team_id, pipeline_id, live_only=True))


def create_pipeline(team_id: int, *, fields: dict[str, Any], created_by: Any) -> Pipeline:
    row = AutoresearchPipeline.objects.create(
        team_id=team_id,
        created_by=created_by,
        iteration_budget_remaining=fields.get("iteration_budget", 50),
        **fields,
    )
    return _pipeline_with_champion(row)


def update_pipeline(team_id: int, pipeline_id: str | UUID, *, fields: dict[str, Any]) -> Pipeline:
    row = _pipeline_row(team_id, pipeline_id, live_only=True)
    for key, value in fields.items():
        setattr(row, key, value)
    row.save()
    return _pipeline_with_champion(row)


def delete_pipeline(team_id: int, pipeline_id: str | UUID) -> None:
    _pipeline_row(team_id, pipeline_id, live_only=True).delete()


def pipeline_has_models(team_id: int, pipeline_id: str | UUID) -> bool:
    """Whether any model has been trained for this pipeline yet.

    The model-defining fields freeze once this is true — scoring keeps loading the trained
    artifact, so changing them would silently answer a different question.
    """
    return _pipeline_row(team_id, pipeline_id, live_only=True).models.exists()


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


def resolve_action_target(project_id: int, action_id: Any) -> tuple[str, int]:
    """Resolve an action target to ``(action_name, action_id)``, scoped to the project.

    Actions live on the project's root team, so the lookup matches the labeler's
    (``team__project_id``) rather than the pipeline's own team, which would miss them from
    any other environment of the project.

    Raises ``PipelineNotFound`` when the action is missing, soft-deleted, or belongs to another
    project, so a foreign action id cannot be probed through this endpoint, and ``InvalidTarget``
    when a step could match the product's own prediction event: the labeler and online
    validation exclude that event from every scan, so such a target could never be
    observed as an outcome.
    """
    try:
        action = Action.objects.get(id=action_id, team__project_id=project_id, deleted=False)
    except (Action.DoesNotExist, ValueError, TypeError, OverflowError):
        raise PipelineNotFound(f"Action {action_id} was not found in this project.")
    step_events = action.get_step_events()
    if any(event is None or event == PREDICTION_EVENT_NAME for event in step_events):
        raise InvalidTarget(
            f"Action {action_id} has a step that can match '{PREDICTION_EVENT_NAME}'. "
            "Every step of a target action must name an event other than the prediction event."
        )
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
    user: User,
) -> ResolvedTemplate:
    team = Team.objects.get(pk=team_id)
    try:
        resolved = templates_module.resolve_template(
            team=team,
            template_key=template_key,
            target_event_override=target_event_override,
            horizon_days_override=horizon_days_override,
            user=user,
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
        training_lookback_days=resolved.training_lookback_days,
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
    user: User,
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
        user=user,
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
    qs = AutoresearchModel.objects.for_team(team_id).order_by("-created_at")
    if pipeline_id:
        qs = qs.filter(pipeline_id=_as_uuid(pipeline_id))
    count = qs.count()
    return [_model_to_contract(row) for row in qs[offset : offset + limit]], count


def get_model(team_id: int, model_id: str | UUID, *, pipeline_id: str | UUID | None = None) -> Model | None:
    model_uuid = _as_uuid(model_id)
    if model_uuid is None:
        return None
    qs = AutoresearchModel.objects.for_team(team_id).filter(pk=model_uuid)
    if pipeline_id:
        qs = qs.filter(pipeline_id=_as_uuid(pipeline_id))
    row = qs.first()
    return _model_to_contract(row) if row else None


# ── Operational runs ───────────────────────────────────────────────────────


def list_runs(team_id: int, *, pipeline_id: str | UUID | None, offset: int, limit: int) -> tuple[list[Run], int]:
    qs = AutoresearchRun.objects.for_team(team_id).order_by("-created_at")
    if pipeline_id:
        qs = qs.filter(pipeline_id=_as_uuid(pipeline_id))
    count = qs.count()
    return [_run_to_contract(row) for row in qs[offset : offset + limit]], count


def get_run(team_id: int, run_id: str | UUID, *, pipeline_id: str | UUID | None = None) -> Run | None:
    run_uuid = _as_uuid(run_id)
    if run_uuid is None:
        return None
    qs = AutoresearchRun.objects.for_team(team_id).filter(pk=run_uuid)
    if pipeline_id:
        qs = qs.filter(pipeline_id=_as_uuid(pipeline_id))
    row = qs.first()
    return _run_to_contract(row) if row else None


# ── Training runs ──────────────────────────────────────────────────────────


def list_training_runs(
    team_id: int, *, pipeline_id: str | UUID | None, offset: int, limit: int
) -> tuple[list[TrainingRun], int]:
    qs = AutoresearchTrainingRun.objects.for_team(team_id).prefetch_related("iterations").order_by("-created_at")
    if pipeline_id:
        qs = qs.filter(pipeline_id=_as_uuid(pipeline_id))
    count = qs.count()
    return [_training_run_to_contract(row) for row in qs[offset : offset + limit]], count


def get_training_run(
    team_id: int, training_run_id: str | UUID, *, pipeline_id: str | UUID | None = None
) -> TrainingRun | None:
    try:
        return _training_run_to_contract(_training_run_row(team_id, training_run_id, pipeline_id=pipeline_id))
    except TrainingRunNotFound:
        return None


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


def record_iteration(
    team_id: int, training_run_id: str | UUID, *, pipeline_id: str | UUID | None = None, fields: dict[str, Any]
) -> Iteration:
    """Record one iteration of an open run. Idempotent on ``iteration_number``."""
    recipe_snapshot = fields["recipe_snapshot"]
    model_spec = fields["model_spec"]
    recipe_hash = hashlib.sha256(
        json.dumps({"recipe": recipe_snapshot, "spec": model_spec}, sort_keys=True).encode()
    ).hexdigest()
    iteration_number = fields["iteration_number"]

    # Completion locks the run row and freezes it. Recording takes the same lock so the status
    # check and the upsert see one state: an iteration can no longer land on a run that
    # completed in between and go missing from its champion selection and summary.
    with transaction.atomic():
        training_run = _training_run_row(
            team_id, training_run_id, pipeline_id=pipeline_id, with_iterations=False, for_update=True
        )
        if training_run.status != AutoresearchTrainingRun.Status.RUNNING:
            raise AutoresearchConflict("Can only record iterations on a running training run.")

        recorded = AutoresearchIteration.objects.filter(training_run=training_run)
        is_new_number = not recorded.filter(iteration_number=iteration_number).exists()
        if is_new_number and recorded.count() >= training_run.iteration_budget:
            raise AutoresearchConflict(
                f"Training run has used its iteration budget of {training_run.iteration_budget}. "
                "Re-sending a recorded iteration_number still updates that iteration."
            )

        defaults: dict[str, Any] = {
            "pipeline": training_run.pipeline,
            "recipe_hash": recipe_hash,
            "recipe_snapshot": recipe_snapshot,
            "model_spec": model_spec,
            "train_score": fields.get("train_score"),
            "holdout_score": fields.get("holdout_score"),
            "status": fields["status"],
            "agent_description": fields.get("agent_description", ""),
            "agent_confidence": fields.get("agent_confidence"),
        }
        # A re-send that omits parent_suggestion keeps the attribution it recorded the first
        # time; only an explicit null clears it.
        parent_suggestion = None
        if "parent_suggestion" in fields:
            parent_suggestion = _parent_suggestion_row(team_id, training_run, fields["parent_suggestion"])
            defaults["parent_suggestion"] = parent_suggestion

        iteration, _ = AutoresearchIteration.objects.update_or_create(
            team_id=team_id,
            training_run=training_run,
            iteration_number=iteration_number,
            defaults=defaults,
        )

        # Spawning an iteration from a suggestion is itself acting on it, so the suggestion
        # advances even if the agent never calls the respond endpoint.
        if parent_suggestion and parent_suggestion.status in (
            AutoresearchSuggestion.Status.QUEUED,
            AutoresearchSuggestion.Status.PICKED_UP,
        ):
            parent_suggestion.status = AutoresearchSuggestion.Status.ACTED_ON
            parent_suggestion.save(update_fields=["status", "updated_at"])

    return _iteration_to_contract(iteration)


def _parent_suggestion_row(
    team_id: int, training_run: AutoresearchTrainingRun, suggestion_id: Any
) -> AutoresearchSuggestion | None:
    """The suggestion an iteration acts on, scoped to the run's pipeline so a foreign id cannot attach."""
    if not suggestion_id:
        return None
    suggestion_uuid = _as_uuid(suggestion_id)
    suggestion = None
    if suggestion_uuid is not None:
        suggestion = (
            AutoresearchSuggestion.objects.for_team(team_id)
            .filter(id=suggestion_uuid, pipeline=training_run.pipeline)
            .first()
        )
    if suggestion is None:
        raise AutoresearchConflict("parent_suggestion not found on this pipeline.")
    return suggestion


def complete_run(
    team_id: int,
    training_run_id: str | UUID,
    *,
    pipeline_id: str | UUID | None = None,
    best_iteration_id: Any = None,
    model_explanation: dict[str, Any] | None = None,
    recommended_next: str = "",
    distillation: str = "",
) -> TrainingRun:
    """Finalize a run. Promotion is server-side, so an agent cannot set the champion."""
    # Promotion imports the inference sandbox, and with it pandas and pyarrow; the router imports
    # this facade on the first request, so the heavy chain loads only when a run completes.
    from ..training.promotion import PromotionError, complete_training_run  # noqa: PLC0415

    training_run = _training_run_row(team_id, training_run_id, pipeline_id=pipeline_id, with_iterations=False)
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
    if training_run.status != AutoresearchTrainingRun.Status.COMPLETED:
        # The TaskRun failure handler won the race for the row lock, so promotion answered with
        # its no-op and the run is failed, not completed.
        raise AutoresearchConflict("Training run failed before it could be completed.")
    return _training_run_to_contract(training_run)


def training_run_history(team_id: int, pipeline_id: str | UUID, *, limit: int = 5) -> TrainingRunHistory:
    """Prior completed runs a new run reads to orient.

    This pipeline's own history first, backfilled with same-target sibling pipelines on the
    team, so a fresh pipeline still inherits what the team already learned about the target.
    """
    pipeline = _pipeline_row(team_id, pipeline_id)
    limit = max(1, min(limit, HISTORY_LIMIT_MAX))

    completed = (
        AutoresearchTrainingRun.objects.for_team(team_id)
        .filter(status=AutoresearchTrainingRun.Status.COMPLETED)
        .select_related("pipeline")
        .prefetch_related("iterations")
    )
    # Postgres puts NULLs first on a bare DESC, so an undated completed run would outrank every
    # dated one; the id breaks ties so a page is the same on every read.
    newest_first = (F("completed_at").desc(nulls_last=True), "-id")
    runs = list(completed.filter(pipeline=pipeline).order_by(*newest_first)[:limit])
    remaining = limit - len(runs)
    if remaining > 0:
        runs += list(
            completed.filter(_same_target_as(pipeline)).exclude(pipeline=pipeline).order_by(*newest_first)[:remaining]
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


def _same_target_as(pipeline: AutoresearchPipeline) -> Q:
    """Sibling pipelines that predict the same outcome, not merely the same display name.

    An action and an event can share a name, so an action target matches on its id, and an
    event target also accepts the empty definition creation stored before it was normalized.
    """
    definition = pipeline.target_definition or {}
    if definition.get("type") == "action":
        return Q(
            pipeline__target_definition__type="action",
            pipeline__target_definition__action_id=definition.get("action_id"),
        )
    return Q(pipeline__target_event=pipeline.target_event) & (
        Q(pipeline__target_definition__type="event") | ~Q(pipeline__target_definition__has_key="type")
    )


# ── Feature materialization ────────────────────────────────────────────────


def materialize_features(
    team_id: int,
    training_run_id: str | UUID,
    *,
    pipeline_id: str | UUID | None = None,
    features_sql: str,
    user: User,
) -> MaterializedFeatures:
    """Run ``features_sql`` server-side and write the parquet into this run's sandbox.

    The rows never pass through the agent's context and there is no row cap. The destination
    paths are fixed by the framework — the agent supplies the query, never where it lands.
    """
    # The inference sandbox imports pandas and pyarrow; the router imports this module for
    # every web worker, so the heavy path loads only when a run materializes.
    from ..inference.sandbox import SandboxInferenceError, label_classes, materialize_training_data  # noqa: PLC0415

    training_run = _training_run_row(team_id, training_run_id, pipeline_id=pipeline_id, with_iterations=False)
    if training_run.status != AutoresearchTrainingRun.Status.RUNNING:
        raise AutoresearchConflict("Can only materialize features for a running training run.")
    validate_features_sql(features_sql)

    sandbox_id = _resolve_run_sandbox_id(training_run)
    team = Team.objects.get(pk=team_id)
    try:
        data = materialize_training_data(team=team, pipeline=training_run.pipeline, feature_sql=features_sql, user=user)
    except (SandboxInferenceError, RecipeValidationError) as exc:
        raise AutoresearchConflict(f"Feature materialization failed: {exc}") from exc
    if not data.train_rows:
        raise AutoresearchConflict("features_sql produced no training rows.")
    if not data.feature_cols:
        raise AutoresearchConflict("features_sql produced no numeric feature columns.")
    # The folds are fixed per person, so another features_sql cannot repair a split that cannot
    # be fitted or scored. Refusing here tells the agent the population is too thin instead of
    # letting it spend the run on iterations completion can never score.
    if not data.holdout_rows:
        raise AutoresearchConflict("The population is too small to hold out an evaluation set. Widen the population.")
    if len(label_classes(data.train_rows)) < 2:
        raise AutoresearchConflict(
            "The training set has only one label class, so no model can be fitted. Widen the population."
        )
    if len(label_classes(data.holdout_rows)) < 2:
        raise AutoresearchConflict(
            "The holdout set has only one label class, so no holdout AUC can be computed. Widen the population."
        )

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
    from products.tasks.backend.facade import api as tasks_facade  # noqa: PLC0415

    if not training_run.task_run_id:
        raise AutoresearchConflict("This training run has no sandbox (e.g. a stub run). Cannot materialize features.")
    task_run = tasks_facade.get_task_run(training_run.task_run_id)
    if task_run is None:
        raise AutoresearchConflict("Sandbox task run not found for this training run.")
    state = task_run.state if isinstance(task_run.state, dict) else {}
    if str(state.get("autoresearch_training_run_id")) != str(training_run.id):
        raise AutoresearchConflict("Sandbox does not belong to this training run.")
    sandbox_id = state.get("sandbox_id")
    if not sandbox_id:
        raise AutoresearchConflict("Sandbox is not ready yet — try again once the agent has started.")
    return str(sandbox_id)


def _write_feature_parquets(sandbox_id: str, data: Any) -> dict[str, str]:
    """Serialize the train/holdout matrices to parquet and write them into the agent's sandbox."""
    # Same reason as in materialize_features: the sandbox providers and pandas stay off the
    # router's import path.
    from products.tasks.backend.facade.sandbox import (  # noqa: PLC0415
        SandboxExecutionError,
        SandboxNotFoundError,
        SandboxNotRunningError,
        SandboxTimeoutError,
        get_sandbox_class_for_sandbox_id,
    )

    from ..inference.sandbox import SandboxInferenceError, features_parquet, labels_parquet  # noqa: PLC0415

    try:
        sandbox = get_sandbox_class_for_sandbox_id(sandbox_id).get_by_id(sandbox_id)
    except Exception as exc:
        raise AutoresearchConflict(f"Could not connect to the run's sandbox: {exc}") from exc
    try:
        files = {
            "train_features_path": ("train_features.parquet", features_parquet(data.train_rows, data.feature_cols)),
            "train_labels_path": ("train_labels.parquet", labels_parquet(data.train_rows)),
            "holdout_features_path": (
                "holdout_features.parquet",
                features_parquet(data.holdout_rows, data.feature_cols),
            ),
            "holdout_labels_path": ("holdout_labels.parquet", labels_parquet(data.holdout_rows)),
        }
    except SandboxInferenceError as exc:
        raise AutoresearchConflict(f"Feature materialization failed: {exc}") from exc
    # Each request gets its own directory, so two overlapping materializations cannot read each
    # other's files, and a request that fails part-way leaves nothing at a path it returned.
    directory = f"{_AGENT_FEATURE_DIR}/{uuid4().hex}"
    paths: dict[str, str] = {}
    for key, (name, content) in files.items():
        path = f"{directory}/{name}"
        try:
            result = sandbox.write_file(path, content)
        except (SandboxNotRunningError, SandboxExecutionError, SandboxNotFoundError, SandboxTimeoutError) as exc:
            raise AutoresearchConflict(f"Failed to write {path} into the sandbox: {exc}") from exc
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


def list_artifacts(team_id: int, training_run_id: str | UUID, *, pipeline_id: str | UUID | None = None) -> ArtifactList:
    training_run = _training_run_row(team_id, training_run_id, pipeline_id=pipeline_id, with_iterations=False)
    paths = artifact_store.list_artifacts(_bundle_prefix(team_id, training_run))
    return ArtifactList(paths=paths, count=len(paths))


def write_artifact(
    team_id: int,
    training_run_id: str | UUID,
    *,
    pipeline_id: str | UUID | None = None,
    path: str,
    content_base64: str,
) -> StoredArtifact:
    """Store one file of the run's bundle. The bundle freezes once the run leaves ``running``."""
    try:
        content = base64.b64decode(content_base64, validate=True)
    except Exception as exc:
        raise AutoresearchConflict("content_base64 is not valid base64.") from exc
    try:
        rel = artifact_store.normalize_artifact_path(path)
    except artifact_store.InvalidArtifact as exc:
        raise InvalidArtifactPath(str(exc)) from exc
    if rel == artifact_store.MODEL_PKL:
        # The fitted model is written by the framework after completion. An agent-written model.pkl
        # would make scoring skip its self-healing fit and serve those bytes on every cadence.
        raise InvalidArtifactPath(f"{artifact_store.MODEL_PKL} is written by the framework and cannot be uploaded.")
    if rel == artifact_store.FEATURES_SQL:
        _require_runnable_features_sql(content)
    # Completion validates and freezes the bundle under the run row lock. Writing under the same
    # lock means an upload that started while the run was RUNNING cannot land after completion
    # read the bundle.
    with transaction.atomic():
        training_run = _running_run_for_write(team_id, training_run_id, pipeline_id=pipeline_id)
        prefix = _bundle_prefix(team_id, training_run)
        existing = artifact_store.list_artifacts(prefix)
        if rel not in existing and len(existing) >= MAX_BUNDLE_FILES:
            raise AutoresearchConflict(
                f"This bundle already holds {MAX_BUNDLE_FILES} files. Delete a file before uploading another."
            )
        try:
            stored = artifact_store.write_artifact(prefix, rel, content)
        except artifact_store.InvalidArtifact as exc:
            raise InvalidArtifactPath(str(exc)) from exc
        except ObjectStorageError as exc:
            raise ArtifactStorageUnavailable(f"The artifact could not be stored: {exc}") from exc
    return StoredArtifact(path=stored.path, size_bytes=stored.size_bytes, sha256=stored.sha256)


def _require_runnable_features_sql(content: bytes) -> None:
    """Refuse feature SQL the fit would refuse, so a champion never lands without a model."""
    from ..inference.sandbox import SandboxInferenceError, validate_runnable_feature_sql  # noqa: PLC0415

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return  # the store refuses the bytes with its own message
    try:
        validate_runnable_feature_sql(text, source=artifact_store.FEATURES_SQL)
    except SandboxInferenceError as exc:
        raise InvalidArtifactPath(str(exc)) from exc


def _running_run_for_write(
    team_id: int, training_run_id: str | UUID, *, pipeline_id: str | UUID | None
) -> AutoresearchTrainingRun:
    training_run = _training_run_row(
        team_id, training_run_id, pipeline_id=pipeline_id, with_iterations=False, for_update=True
    )
    if training_run.status != AutoresearchTrainingRun.Status.RUNNING:
        raise AutoresearchConflict("The bundle is frozen because the training run is no longer running.")
    return training_run


def read_artifact(
    team_id: int, training_run_id: str | UUID, *, pipeline_id: str | UUID | None = None, path: str
) -> ArtifactContent:
    training_run = _training_run_row(team_id, training_run_id, pipeline_id=pipeline_id, with_iterations=False)
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


def delete_artifact(
    team_id: int, training_run_id: str | UUID, *, pipeline_id: str | UUID | None = None, path: str
) -> ArtifactDeleteResult:
    try:
        normalized = artifact_store.normalize_artifact_path(path)
    except artifact_store.InvalidArtifactPath as exc:
        raise InvalidArtifactPath(str(exc)) from exc
    with transaction.atomic():
        training_run = _running_run_for_write(team_id, training_run_id, pipeline_id=pipeline_id)
        try:
            deleted = artifact_store.delete_artifact(_bundle_prefix(team_id, training_run), normalized)
        except ObjectStorageError as exc:
            raise ArtifactStorageUnavailable(f"The artifact could not be deleted: {exc}") from exc
    return ArtifactDeleteResult(path=normalized, deleted=deleted)


# ── Recipe validation surface for the presentation layer ───────────────────

# The semantic population kinds the labeler can compile. Presentation validates a submitted
# spec against this so an uncompilable population is refused at creation, not at query time.
POPULATION_KINDS = _POPULATION_KINDS

# The event this product emits. It is excluded from every labeler and validation scan, so it
# can never be a target.
PREDICTION_EVENT_NAME = _PREDICTION_EVENT_NAME


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
TEMPLATE_KEY_CHOICES = _TemplateKey.choices
# A plain list, not choices: the serializer explains why `code` is not an enum.
VALIDATION_WARNING_CODES = [code.value for code in _ValidationWarningCode]
MODEL_ROLE_CHOICES = AutoresearchModel.Role.choices
TRAINING_RUN_STATUS_CHOICES = AutoresearchTrainingRun.Status.choices
ITERATION_STATUS_CHOICES = AutoresearchIteration.Status.choices
RUN_TYPE_CHOICES = AutoresearchRun.RunType.choices
RUN_STATUS_CHOICES = AutoresearchRun.Status.choices
