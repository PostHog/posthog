"""The realized results a training run reads before it starts.

The backend computes this from the validation history, so the agent sees how its models
perform as served without a tool call. The brief tells the agent to use it to choose a
direction, never as a metric to iterate against: the next run's holdout covers the same
recent dates, so tuning against realized results tunes against the holdout.
"""

from datetime import date
from typing import Any
from uuid import UUID

from django.db.models import Max
from django.db.models.fields.json import KT

from posthog.dataclasses import frozen

from products.autoresearch.backend.dataset.labeling import TARGET_RELATIVE_KINDS
from products.autoresearch.backend.evaluation.history import latest_validation_runs
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline, AutoresearchRun
from products.autoresearch.backend.training.shadow_set import shadow_set

# Validated groups read for this pipeline. The per-model cap below applies after this.
OWN_VALIDATION_GROUPS = 60
REALIZED_DATES_PER_MODEL = 14
RELATED_PIPELINES_LIMIT = 5
REALIZED_DATES_PER_RELATED_PIPELINE = 7

RELATION_SAME_TARGET = "same target"
RELATION_SAME_POPULATION = "same population"


@frozen
class RealizedDate:
    prediction_date: date
    holdout_score: float | None
    realized_auc: float | None
    realized_auc_ci_low: float | None
    realized_auc_ci_high: float | None
    n_scored: int
    n_positive: int
    base_rate: float
    mean_p_y: float | None


@frozen
class RealizedModel:
    label: str
    holdout_score: float | None
    promoted_on: date | None
    dates: list[RealizedDate]


@frozen
class RelatedPipeline:
    name: str
    target_event: str
    horizon_days: int
    relation: str
    latest_date: date
    dates: list[RealizedDate]


@frozen
class RealizedContext:
    models: list[RealizedModel]
    related: list[RelatedPipeline]

    @property
    def is_empty(self) -> bool:
        return not self.related and not any(m.dates for m in self.models)


def build_realized_context(pipeline: AutoresearchPipeline) -> RealizedContext:
    return RealizedContext(models=_own_models(pipeline), related=_related_pipelines(pipeline))


def _own_models(pipeline: AutoresearchPipeline) -> list[RealizedModel]:
    members = shadow_set(pipeline)
    if not members:
        return []
    dates_by_model: dict[UUID, list[RealizedDate]] = {m.pk: [] for m in members}
    holdout = {m.pk: m.holdout_score for m in members}
    for run in latest_validation_runs(pipeline.team_id, pipeline, limit=OWN_VALIDATION_GROUPS):
        for model_id, metrics in (run.metrics.get("per_model") or {}).items():
            model_dates = dates_by_model.get(UUID(model_id))
            if model_dates is not None and len(model_dates) < REALIZED_DATES_PER_MODEL:
                model_dates.append(_realized_date(run, metrics, holdout_score=holdout[UUID(model_id)]))
    return [
        RealizedModel(
            label=_member_label(m),
            holdout_score=m.holdout_score,
            promoted_on=m.promoted_at.date() if m.promoted_at else None,
            dates=dates_by_model[m.pk],
        )
        for m in members
    ]


def _member_label(model: AutoresearchModel) -> str:
    if model.role == AutoresearchModel.Role.CHAMPION:
        return "champion"
    if model.role == AutoresearchModel.Role.ARCHIVED:
        return "previous champion"
    return "shadow challenger"


def _related_pipelines(pipeline: AutoresearchPipeline) -> list[RelatedPipeline]:
    """
    Pipelines of the same team that predict the same outcome at another horizon, or that
    score the same population for another target. Same target ranks first, then the nearest
    horizon, then the newest realized result. Only pipelines with a realized result qualify.
    """
    candidates: list[tuple[AutoresearchPipeline, str]] = []
    for other in AutoresearchPipeline.objects.for_team(pipeline.team_id).exclude(pk=pipeline.pk):
        if _target_key(other) == _target_key(pipeline):
            candidates.append((other, RELATION_SAME_TARGET))
        elif _shares_population(other, pipeline):
            candidates.append((other, RELATION_SAME_POPULATION))
    if not candidates:
        return []

    latest = {
        pipeline_id: date.fromisoformat(latest_date)
        for pipeline_id, latest_date in AutoresearchRun.objects.for_team(pipeline.team_id)
        .filter(
            pipeline_id__in=[other.pk for other, _ in candidates],
            run_type=AutoresearchRun.RunType.VALIDATION,
            status=AutoresearchRun.Status.COMPLETED,
            metrics__has_key="prediction_date",
        )
        .values("pipeline_id")
        .annotate(latest=Max(KT("metrics__prediction_date")))
        .values_list("pipeline_id", "latest")
    }
    ranked = sorted(
        ((other, relation) for other, relation in candidates if other.pk in latest),
        key=lambda item: (
            item[1] != RELATION_SAME_TARGET,
            abs(item[0].horizon_days - pipeline.horizon_days),
            -latest[item[0].pk].toordinal(),
        ),
    )[:RELATED_PIPELINES_LIMIT]

    return [
        RelatedPipeline(
            name=other.name,
            target_event=other.target_event,
            horizon_days=other.horizon_days,
            relation=relation,
            latest_date=latest[other.pk],
            dates=_champion_dates(other),
        )
        for other, relation in ranked
    ]


@frozen
class _TargetKey:
    kind: str
    ref: str


def _target_key(pipeline: AutoresearchPipeline) -> _TargetKey:
    """An action and an event can share a name, so an action target is keyed on its id."""
    definition = pipeline.target_definition or {}
    if definition.get("type") == "action":
        return _TargetKey(kind="action", ref=str(definition.get("action_id")))
    return _TargetKey(kind="event", ref=pipeline.target_event)


def _shares_population(other: AutoresearchPipeline, pipeline: AutoresearchPipeline) -> bool:
    """A target-relative population resolves against each pipeline's own target, so equal specs select other people."""
    population = pipeline.training_population or None
    if (population or {}).get("kind") in TARGET_RELATIVE_KINDS:
        return False
    return (other.training_population or None) == population


def _champion_dates(pipeline: AutoresearchPipeline) -> list[RealizedDate]:
    """The model that served each date, so the gap pattern follows what users received."""
    runs = latest_validation_runs(pipeline.team_id, pipeline, limit=REALIZED_DATES_PER_RELATED_PIPELINE)
    served = [
        (run, UUID(model_id), metrics)
        for run in runs
        for model_id, metrics in (run.metrics.get("per_model") or {}).items()
        if metrics.get("emitted_role") == AutoresearchModel.Role.CHAMPION
    ]
    holdout = dict(
        AutoresearchModel.objects.for_team(pipeline.team_id)
        .filter(pipeline=pipeline, pk__in={model_id for _, model_id, _ in served})
        .values_list("id", "holdout_score")
    )
    return [_realized_date(run, metrics, holdout_score=holdout.get(model_id)) for run, model_id, metrics in served]


def _realized_date(run: AutoresearchRun, metrics: dict[str, Any], *, holdout_score: float | None) -> RealizedDate:
    return RealizedDate(
        prediction_date=date.fromisoformat(run.metrics["prediction_date"]),
        holdout_score=holdout_score,
        realized_auc=metrics.get("realized_auc"),
        realized_auc_ci_low=metrics.get("realized_auc_ci_low"),
        realized_auc_ci_high=metrics.get("realized_auc_ci_high"),
        n_scored=int(metrics.get("n_scored") or 0),
        n_positive=int(metrics.get("n_positive") or 0),
        base_rate=float(metrics.get("base_rate") or 0.0),
        mean_p_y=metrics.get("mean_p_y"),
    )
