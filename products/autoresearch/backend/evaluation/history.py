"""The realized history of a pipeline: its completed validation runs, one per validated group."""

from datetime import date
from uuid import UUID

from django.db.models import F, Window
from django.db.models.fields.json import KT
from django.db.models.functions import DenseRank

from products.autoresearch.backend.models import AutoresearchPipeline, AutoresearchRun


def latest_validation_runs(team_id: int, pipeline: AutoresearchPipeline, *, limit: int) -> list[AutoresearchRun]:
    """
    The newest completed validation run per (prediction date, horizon), newest date first.

    ``limit`` bounds the number of groups. When a group was validated more than once, its
    newest completed run holds the current evidence. Each run keeps every model it scored in
    ``metrics["per_model"]``, so a former champion keeps its evidence after a promotion.
    """
    return list(
        AutoresearchRun.objects.for_team(team_id)
        .filter(
            pipeline=pipeline,
            run_type=AutoresearchRun.RunType.VALIDATION,
            status=AutoresearchRun.Status.COMPLETED,
            metrics__has_key="prediction_date",
        )
        .annotate(prediction_date=KT("metrics__prediction_date"), horizon=KT("metrics__horizon_days"))
        .order_by("-prediction_date", "horizon", F("completed_at").desc(nulls_last=True), "-id")
        .distinct("prediction_date", "horizon")[:limit]
    )


def realized_auc_trends(
    team_id: int, model_ids_by_pipeline: dict[UUID, UUID], *, dates: int
) -> dict[UUID, list[tuple[date, float]]]:
    """
    Realized AUC of one model per pipeline on its newest ``dates`` validated prediction dates, oldest first.

    One query for any number of pipelines. A date with no AUC for the model, for example a
    single-class date, is left out. When a date was validated more than once, the newest
    completed run wins.
    """
    if not model_ids_by_pipeline:
        return {}
    runs = (
        AutoresearchRun.objects.for_team(team_id)
        .filter(
            pipeline_id__in=list(model_ids_by_pipeline),
            run_type=AutoresearchRun.RunType.VALIDATION,
            status=AutoresearchRun.Status.COMPLETED,
            metrics__has_key="prediction_date",
        )
        .annotate(
            prediction_date=KT("metrics__prediction_date"),
            date_rank=Window(DenseRank(), partition_by=[F("pipeline_id")], order_by=F("prediction_date").desc()),
        )
        .filter(date_rank__lte=dates)
        .order_by("pipeline_id", "prediction_date", F("completed_at").desc(nulls_last=True), "-id")
        .only("pipeline_id", "metrics", "completed_at")
    )
    seen: set[tuple[UUID, date]] = set()
    trends: dict[UUID, dict[date, float]] = {}
    for run in runs:
        points = trends.setdefault(run.pipeline_id, {})
        prediction_date = date.fromisoformat(run.metrics["prediction_date"])
        if (run.pipeline_id, prediction_date) in seen:
            continue
        seen.add((run.pipeline_id, prediction_date))
        model_metrics = (run.metrics.get("per_model") or {}).get(str(model_ids_by_pipeline[run.pipeline_id])) or {}
        auc = model_metrics.get("realized_auc")
        if isinstance(auc, int | float):
            points[prediction_date] = float(auc)
    return {pipeline_id: sorted(points.items()) for pipeline_id, points in trends.items()}
