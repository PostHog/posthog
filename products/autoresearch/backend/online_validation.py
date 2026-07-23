"""
Online validation: join autoresearch_prediction events to realized target outcomes
after the prediction horizon has elapsed.

Computes per-model: realized AUC, Brier score, expected calibration error (ECE),
and lift@k for both champion and challengers.

Architecture:
- Pure activity functions called by AutoresearchValidationWorkflow (Temporal)
  and the autoresearch_validate_online management command.
- All heavy work (HogQL queries + sklearn metrics) happens inside a single activity;
  nothing large passes through Temporal payloads.
"""

import math
from datetime import date, timedelta
from typing import Any

from django.utils import timezone as django_timezone

import numpy as np
import structlog

from posthog.schema import HogQLQuery

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team.team import Team

from products.autoresearch.backend.labeling import build_target_condition
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline, AutoresearchRun

logger = structlog.get_logger(__name__)

PREDICTION_EVENT_NAME = "autoresearch_prediction"
VALIDATION_QUERY_LIMIT = 50_000


def run_online_validation_for_pipeline(pipeline: AutoresearchPipeline) -> list[AutoresearchRun]:
    """
    Find all matured, unvalidated prediction dates and validate each one.

    A prediction date is "matured" when today >= prediction_date + horizon_days —
    meaning the outcome window has closed and realized labels can be fetched.

    Returns one AutoresearchRun per prediction_date processed and updates
    realized_score / calibration_error on each AutoresearchModel.
    """
    team = pipeline.team
    mature_dates = _find_mature_unvalidated_dates(team, pipeline)

    if not mature_dates:
        logger.info("autoresearch_validation_no_mature_dates", pipeline_id=str(pipeline.pk))
        return []

    results = []
    for prediction_date in sorted(mature_dates):
        run = _validate_one_date(team, pipeline, prediction_date)
        results.append(run)
    return results


def _find_mature_unvalidated_dates(team: Team, pipeline: AutoresearchPipeline) -> list[date]:
    """
    Return prediction dates that have matured but haven't been successfully validated.
    Already-validated dates are tracked as COMPLETED validation AutoresearchRuns with
    metrics['prediction_date'] set.
    """
    matured = _fetch_matured_prediction_dates(team, pipeline)
    if not matured:
        return []

    already_validated = {
        r.metrics.get("prediction_date")
        for r in AutoresearchRun.objects.filter(
            pipeline=pipeline,
            run_type=AutoresearchRun.RunType.VALIDATION,
            status=AutoresearchRun.Status.COMPLETED,
        )
        if r.metrics.get("prediction_date")
    }

    return [d for d in matured if d.isoformat() not in already_validated]


def _fetch_matured_prediction_dates(team: Team, pipeline: AutoresearchPipeline) -> list[date]:
    """
    Query ClickHouse for distinct prediction dates where the horizon has elapsed:
    prediction_date + horizon_days <= today.
    """
    sql = (
        "SELECT DISTINCT toDate(properties['$autoresearch_prediction_date']) AS prediction_date"
        " FROM events"
        " WHERE event = {event_name}"
        " AND properties['$autoresearch_pipeline_id'] = {pipeline_id}"
        " AND addDays(toDate(properties['$autoresearch_prediction_date']), {horizon_days}) <= today()"
        " ORDER BY prediction_date ASC"
    )
    values: dict[str, Any] = {
        "event_name": PREDICTION_EVENT_NAME,
        "pipeline_id": str(pipeline.pk),
        "horizon_days": pipeline.horizon_days,
    }

    try:
        tag_queries(product=Product.AUTORESEARCH, feature=Feature.QUERY)
        runner = HogQLQueryRunner(query=HogQLQuery(query=sql, values=values), team=team)
        result = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
        if not result.results:
            return []
        return [date.fromisoformat(str(row[0])) for row in result.results if row[0]]
    except Exception:
        logger.exception("autoresearch_matured_dates_query_failed", pipeline_id=str(pipeline.pk))
        return []


def _validate_one_date(
    team: Team,
    pipeline: AutoresearchPipeline,
    prediction_date: date,
) -> AutoresearchRun:
    """
    Validate predictions made on prediction_date for all models (champion + challengers).
    Creates an AutoresearchRun record, computes metrics, and updates model records.
    """
    now = django_timezone.now()
    run = AutoresearchRun.objects.create(
        pipeline=pipeline,
        run_type=AutoresearchRun.RunType.VALIDATION,
        status=AutoresearchRun.Status.RUNNING,
        started_at=now,
        metrics={"prediction_date": prediction_date.isoformat()},
    )

    try:
        model_predictions = _fetch_predictions_by_model(team, pipeline, prediction_date)
        realized_labels = _fetch_realized_labels(team, pipeline, prediction_date)

        if not model_predictions:
            logger.warning(
                "autoresearch_validation_no_predictions",
                pipeline_id=str(pipeline.pk),
                prediction_date=prediction_date.isoformat(),
            )
            run.status = AutoresearchRun.Status.COMPLETED
            run.rows_scored = 0
            run.completed_at = django_timezone.now()
            run.metrics["warning"] = "no_predictions_found"
            run.save(update_fields=["status", "rows_scored", "completed_at", "metrics"])
            return run

        per_model_metrics: dict[str, Any] = {}
        total_rows = 0

        for model_id, predictions in model_predictions.items():
            model = AutoresearchModel.objects.filter(pk=model_id, pipeline=pipeline).first()
            if not model:
                continue

            metrics = _compute_validation_metrics(predictions, realized_labels)
            per_model_metrics[model_id] = {
                "model_role": model.role,
                "n_scored": len(predictions),
                **metrics,
            }
            total_rows += len(predictions)
            _update_model_realized_metrics(model, metrics)

        run.status = AutoresearchRun.Status.COMPLETED
        run.rows_scored = total_rows
        run.completed_at = django_timezone.now()
        run.metrics.update(
            {
                "prediction_date": prediction_date.isoformat(),
                "realized_labels_count": len(realized_labels),
                "per_model": per_model_metrics,
            }
        )
        run.save(update_fields=["status", "rows_scored", "completed_at", "metrics"])

        logger.info(
            "autoresearch_validation_complete",
            pipeline_id=str(pipeline.pk),
            prediction_date=prediction_date.isoformat(),
            models_validated=len(per_model_metrics),
            total_rows=total_rows,
        )
        return run

    except Exception:
        run.status = AutoresearchRun.Status.FAILED
        run.completed_at = django_timezone.now()
        run.save(update_fields=["status", "completed_at"])
        logger.exception(
            "autoresearch_validation_failed",
            pipeline_id=str(pipeline.pk),
            prediction_date=prediction_date.isoformat(),
        )
        raise


def _fetch_predictions_by_model(
    team: Team,
    pipeline: AutoresearchPipeline,
    prediction_date: date,
) -> dict[str, dict[str, float]]:
    """
    Return {model_id: {person_id: p_y}} for all predictions emitted on prediction_date.

    Keyed on person_id to match realized labels (also keyed on person_id). Predictions
    carry it as the $autoresearch_person_id property; we fall back to distinct_id for
    events emitted before that property existed (when distinct_id was str(person_id)).
    """
    sql = (
        "SELECT"
        " coalesce(nullIf(properties['$autoresearch_person_id'], ''), distinct_id) AS person_id,"
        " properties['$autoresearch_model_id'] AS model_id,"
        " toFloat(properties['$autoresearch_p_y']) AS p_y"
        " FROM events"
        " WHERE event = {event_name}"
        " AND properties['$autoresearch_pipeline_id'] = {pipeline_id}"
        " AND properties['$autoresearch_prediction_date'] = {prediction_date}"
        " LIMIT {limit}"
    )
    values: dict[str, Any] = {
        "event_name": PREDICTION_EVENT_NAME,
        "pipeline_id": str(pipeline.pk),
        "prediction_date": prediction_date.isoformat(),
        "limit": VALIDATION_QUERY_LIMIT,
    }

    try:
        tag_queries(product=Product.AUTORESEARCH, feature=Feature.QUERY)
        runner = HogQLQueryRunner(query=HogQLQuery(query=sql, values=values), team=team)
        result = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
        if not result.results:
            return {}
    except Exception:
        logger.exception(
            "autoresearch_predictions_query_failed",
            pipeline_id=str(pipeline.pk),
            prediction_date=prediction_date.isoformat(),
        )
        return {}

    model_predictions: dict[str, dict[str, float]] = {}
    for row in result.results:
        person_id, model_id, p_y = row[0], row[1], row[2]
        if not person_id or not model_id or p_y is None:
            continue
        mid = str(model_id)
        if mid not in model_predictions:
            model_predictions[mid] = {}
        model_predictions[mid][str(person_id)] = float(p_y)

    return model_predictions


def _fetch_realized_labels(
    team: Team,
    pipeline: AutoresearchPipeline,
    prediction_date: date,
) -> frozenset[str]:
    """
    Return person_ids that performed the pipeline's target (event or action) in the
    window [prediction_date, prediction_date + horizon_days).

    Keyed on person_id (not distinct_id) to match the prediction events, which
    are emitted with distinct_id = str(person_id) — the feature/score SQL keys
    every scored row on person_id (see labeling.py, sandbox_inference.py).
    Joining on the raw event distinct_id would compare two disjoint key spaces
    and yield all-negative labels (AUC ≈ 0.5 / single-class).
    """
    end_date = prediction_date + timedelta(days=pipeline.horizon_days)
    target_cond, target_values = build_target_condition(
        target_event=pipeline.target_event, target_definition=pipeline.target_definition, team=team
    )
    sql = (
        "SELECT DISTINCT person_id"
        " FROM events"
        f" WHERE {target_cond}"
        " AND toDate(timestamp) >= {start_date}"
        " AND toDate(timestamp) < {end_date}"
    )
    values: dict[str, Any] = {
        "start_date": prediction_date.isoformat(),
        "end_date": end_date.isoformat(),
        **target_values,
    }

    try:
        tag_queries(product=Product.AUTORESEARCH, feature=Feature.QUERY)
        runner = HogQLQueryRunner(query=HogQLQuery(query=sql, values=values), team=team)
        result = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
        if not result.results:
            return frozenset()
        return frozenset(str(row[0]) for row in result.results if row[0])
    except Exception:
        logger.exception(
            "autoresearch_realized_labels_query_failed",
            pipeline_id=str(pipeline.pk),
            prediction_date=prediction_date.isoformat(),
        )
        return frozenset()


def _compute_validation_metrics(
    predictions: dict[str, float],
    realized_labels: frozenset[str],
) -> dict[str, Any]:
    """
    Compute AUC, Brier score, ECE, and lift@k from scored predictions vs realized labels.

    predictions: {distinct_id: p_y}
    realized_labels: distinct_ids that performed the target event in the horizon window
    """
    distinct_ids = list(predictions.keys())
    y_score = np.array([predictions[did] for did in distinct_ids], dtype=np.float64)
    y_true = np.array([1 if did in realized_labels else 0 for did in distinct_ids], dtype=np.int32)

    n = len(y_true)
    n_pos = int(y_true.sum())
    n_neg = n - n_pos
    base_rate = n_pos / n if n > 0 else 0.0

    metrics: dict[str, Any] = {
        "n_scored": n,
        "n_positive": n_pos,
        "n_negative": n_neg,
        "base_rate": round(base_rate, 4),
    }

    if n_pos == 0 or n_neg == 0:
        metrics["warning"] = "single_class_no_auc"
        return metrics

    from sklearn.metrics import brier_score_loss, roc_auc_score

    metrics["realized_auc"] = round(float(roc_auc_score(y_true, y_score)), 4)
    metrics["brier_score"] = round(float(brier_score_loss(y_true, y_score)), 4)
    metrics["calibration_error"] = round(_expected_calibration_error(y_true, y_score), 4)
    metrics["lift_at_10"] = round(_lift_at_k(y_true, y_score, k=0.10), 4)
    metrics["lift_at_20"] = round(_lift_at_k(y_true, y_score, k=0.20), 4)

    return metrics


def _expected_calibration_error(y_true: np.ndarray, y_score: np.ndarray, n_bins: int = 10) -> float:
    """
    Expected Calibration Error (ECE): fraction-weighted mean absolute difference
    between mean predicted probability and actual positive rate within each decile bin.
    """
    n = len(y_true)
    bin_boundaries = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        lo, hi = bin_boundaries[i], bin_boundaries[i + 1]
        mask = (y_score >= lo) & (y_score <= hi) if i == n_bins - 1 else (y_score >= lo) & (y_score < hi)
        if not mask.any():
            continue
        bin_n = int(mask.sum())
        avg_pred = float(y_score[mask].mean())
        actual_rate = float(y_true[mask].mean())
        ece += (bin_n / n) * abs(avg_pred - actual_rate)
    return ece


def _lift_at_k(y_true: np.ndarray, y_score: np.ndarray, k: float) -> float:
    """
    Lift@k: ratio of positives captured in the top-k% of scored users vs random.

    lift@k = (positives in top k%) / (k × total positives)

    A lift of 2.0 at k=10% means the top 10% by score contains 2× as many positives
    as a random 10% sample would.
    """
    n_pos_total = int(y_true.sum())
    if n_pos_total == 0 or k <= 0:
        return 0.0
    n = len(y_true)
    cutoff = max(1, math.ceil(n * k))
    top_k_idx = np.argsort(y_score)[::-1][:cutoff]
    positives_captured = int(y_true[top_k_idx].sum())
    random_expected = k * n_pos_total
    return positives_captured / random_expected


def _update_model_realized_metrics(model: AutoresearchModel, metrics: dict[str, Any]) -> None:
    """
    Persist validation metrics to the model record.

    On first realized validation (is_preliminary=True), clears the preliminary flag
    and sets realized_score. Subsequent validations update realized_score to the latest.
    """
    auc = metrics.get("realized_auc")
    cal_error = metrics.get("calibration_error")

    existing = model.metrics or {}
    existing["realized"] = metrics

    update_fields = ["metrics", "updated_at"]

    if auc is not None:
        model.realized_score = auc
        update_fields.append("realized_score")
        if model.is_preliminary:
            model.is_preliminary = False
            update_fields.append("is_preliminary")

    if cal_error is not None:
        model.calibration_error = cal_error
        update_fields.append("calibration_error")

    model.metrics = existing
    model.save(update_fields=update_fields)

    logger.info(
        "autoresearch_model_realized_metrics_updated",
        model_id=str(model.pk),
        role=model.role,
        realized_auc=auc,
        calibration_error=cal_error,
        is_preliminary=model.is_preliminary,
    )
