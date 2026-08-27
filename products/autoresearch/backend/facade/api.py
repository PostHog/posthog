"""
Public facade for autoresearch.

Every consumer — this product's own presentation layer included — reaches autoresearch
data and behavior through this module. Functions take and return the frozen contracts in
``contracts.py``; ORM rows never leave.

Scope is set at the entry boundary, so every read and write here takes ``team_id`` and
filters on it. Business rules live in the modules behind this facade, not in the views.
"""

from typing import Any
from uuid import UUID

from posthog.models.team import Team

from products.actions.backend.models.action import Action

from ..dataset import templates as templates_module
from ..dataset.labeling import POPULATION_KINDS as _POPULATION_KINDS
from ..dataset.validation import validate_pipeline_definition as _validate_pipeline_definition
from ..models import AutoresearchModel, AutoresearchPipeline
from .contracts import (
    AutoresearchConflict,
    Pipeline,
    PipelineNotFound,
    PipelineValidation,
    PipelineWrite,
    ResolvedTemplate,
    TemplateInfo,
    ValidationWarning,
)

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


# ── Row lookups (internal) ─────────────────────────────────────────────────


def _pipeline_row(team_id: int, pipeline_id: str | UUID, *, live_only: bool = False) -> AutoresearchPipeline:
    """One pipeline in this team.

    ``live_only`` excludes archived rows, which is what the pipeline's own detail routes do: an
    archived pipeline is gone as far as they are concerned, so acting on one is a 404 rather than
    a refusal that admits it exists. Routes nested under a pipeline id keep seeing archived rows,
    so they can explain why the write is refused.
    """
    qs = AutoresearchPipeline.objects.for_team(team_id)
    if live_only:
        qs = qs.exclude(status=AutoresearchPipeline.Status.ARCHIVED)
    try:
        return qs.get(pk=str(pipeline_id))
    except (AutoresearchPipeline.DoesNotExist, ValueError, TypeError):
        raise PipelineNotFound("Pipeline not found.")


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


# ── Recipe validation surface for the presentation layer ───────────────────

# The semantic population kinds the labeler can compile. Presentation validates a submitted
# spec against this so an uncompilable population is refused at creation, not at query time.
POPULATION_KINDS = _POPULATION_KINDS


# ── Choice vocabularies for the presentation layer ─────────────────────────

# The (value, label) pairs behind each status-like field. Presentation declares its
# ChoiceFields from these so the generated enum components keep the names and labels the
# model-bound serializers produced — including the one shared with another product, which
# `ENUM_NAME_OVERRIDES` pins by value set.
PIPELINE_STATUS_CHOICES = AutoresearchPipeline.Status.choices
