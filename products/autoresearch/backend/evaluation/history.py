"""The realized history of a pipeline: its completed validation runs, one per validated group."""

from django.db.models import F
from django.db.models.fields.json import KT

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
