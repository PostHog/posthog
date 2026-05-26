"""
Inference: load the champion model recipe, score the inference population via
HogQL, and emit autoresearch_prediction events per (user, pipeline, model).

Architecture:
- This module contains the pure activity functions.
- The Temporal inference workflow (temporal/workflows.py) calls these functions.
- The management command (management/commands/autoresearch_score.py) also calls
  them directly for local headless testing.

Event shape:
    event: autoresearch_prediction
    distinct_id: <person distinct_id>
    properties:
        $autoresearch_pipeline_id:     str (UUID)
        $autoresearch_model_id:        str (UUID)
        $autoresearch_model_role:      "champion" | "challenger"
        $autoresearch_target_event:    str
        $autoresearch_horizon_days:    int
        $autoresearch_p_y:             float  ← the score
        $autoresearch_prediction_date: str (YYYY-MM-DD)
        $autoresearch_features_hash:   str (SHA-256 of feature row)
"""

import json
import math
import hashlib
import importlib
from datetime import date
from typing import Any

from django.utils import timezone as django_timezone

import numpy as np
import structlog

from posthog.schema import HogQLQuery

from posthog.api.capture import capture_internal
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team.team import Team

from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline, AutoresearchRun

logger = structlog.get_logger(__name__)

EVENT_SOURCE = "autoresearch_inference"
PREDICTION_EVENT_NAME = "autoresearch_prediction"

# Batch size for ClickHouse feature queries — keeps memory bounded
FEATURE_QUERY_LIMIT = 10_000


def run_inference_for_pipeline(
    pipeline: AutoresearchPipeline,
    model: AutoresearchModel,
) -> AutoresearchRun:
    """
    Top-level inference entry point. Creates an AutoresearchRun, scores users,
    emits prediction events, and records metrics.

    Called by:
    - AutoresearchPipelineViewSet.run_inference (API)
    - autoresearch_score management command
    - AutoresearchInferenceWorkflow Temporal activity (future)
    """
    now = django_timezone.now()
    run = AutoresearchRun.objects.create(
        pipeline=pipeline,
        model=model,
        run_type=AutoresearchRun.RunType.INFERENCE,
        status=AutoresearchRun.Status.RUNNING,
        started_at=now,
    )

    try:
        team = pipeline.team
        rows_scored, score_distribution = _score_and_emit(
            team=team,
            pipeline=pipeline,
            model=model,
            prediction_date=date.today(),
        )

        run.status = AutoresearchRun.Status.COMPLETED
        run.rows_scored = rows_scored
        run.metrics = {
            "score_distribution": score_distribution,
            "stub": model.model_recipe.get("stub", False),
        }
        run.completed_at = django_timezone.now()
        run.save(update_fields=["status", "rows_scored", "metrics", "completed_at"])

        pipeline.last_scored_at = run.completed_at
        pipeline.save(update_fields=["last_scored_at", "updated_at"])

        logger.info(
            "autoresearch_inference_complete",
            pipeline_id=str(pipeline.pk),
            model_id=str(model.pk),
            rows_scored=rows_scored,
        )
        return run

    except Exception:
        run.status = AutoresearchRun.Status.FAILED
        run.completed_at = django_timezone.now()
        run.save(update_fields=["status", "completed_at"])
        logger.exception("autoresearch_inference_failed", pipeline_id=str(pipeline.pk))
        raise


def _score_and_emit(
    team: Team,
    pipeline: AutoresearchPipeline,
    model: AutoresearchModel,
    prediction_date: date,
) -> tuple[int, dict[str, Any]]:
    """
    Fetch feature rows, compute scores, emit prediction events.
    Returns (rows_scored, score_distribution_summary).
    """
    feature_rows = _fetch_feature_rows(team=team, pipeline=pipeline, model=model)

    if not feature_rows:
        logger.warning(
            "autoresearch_no_feature_rows",
            pipeline_id=str(pipeline.pk),
            team_id=team.pk,
        )
        return 0, {}

    recipe = model.model_recipe
    if recipe.get("stub"):
        scored = _score_rows(feature_rows=feature_rows, recipe=recipe)
    else:
        positive_ids = _fetch_label_distinct_ids(team=team, pipeline=pipeline)
        scored = _fit_and_score(feature_rows=feature_rows, positive_ids=positive_ids, recipe=recipe)

    scores = [s["p_y"] for s in scored]
    score_distribution = _summarize_scores(scores)

    token = team.api_token
    prediction_date_str = prediction_date.isoformat()

    emitted = 0
    errors = 0
    for row in scored:
        try:
            features_hash = hashlib.sha256(
                json.dumps({k: v for k, v in row.items() if k != "p_y"}, sort_keys=True).encode()
            ).hexdigest()[:16]

            props = {
                "$autoresearch_pipeline_id": str(pipeline.pk),
                "$autoresearch_model_id": str(model.pk),
                "$autoresearch_model_role": model.role,
                "$autoresearch_target_event": pipeline.target_event,
                "$autoresearch_horizon_days": pipeline.horizon_days,
                "$autoresearch_p_y": row["p_y"],
                "$autoresearch_prediction_date": prediction_date_str,
                "$autoresearch_features_hash": features_hash,
            }
            response = capture_internal(
                token=token,
                event_name=PREDICTION_EVENT_NAME,
                event_source=EVENT_SOURCE,
                distinct_id=row["distinct_id"],
                timestamp=django_timezone.now(),
                properties=props,
                process_person_profile=False,
            )
            response.raise_for_status()
            emitted += 1
        except Exception:
            errors += 1
            logger.exception(
                "autoresearch_prediction_emit_failed",
                pipeline_id=str(pipeline.pk),
                distinct_id=row.get("distinct_id"),
            )

    if errors:
        logger.warning(
            "autoresearch_prediction_emit_partial",
            pipeline_id=str(pipeline.pk),
            emitted=emitted,
            errors=errors,
        )

    return emitted, score_distribution


def _fetch_feature_rows(
    team: Team,
    pipeline: AutoresearchPipeline,
    model: AutoresearchModel,
) -> list[dict[str, Any]]:
    """
    Run the recipe's feature SQL via HogQL and return a list of dicts,
    one per user with column names as keys.

    For the stub recipe the SQL is a templated aggregate query. In a real
    implementation the recipe compiler would validate and sanitize the SQL
    before running it here.
    """
    recipe = model.model_recipe
    feature_sql = recipe.get("feature_sql", "")

    if not feature_sql:
        logger.warning("autoresearch_empty_feature_sql", pipeline_id=str(pipeline.pk))
        return []

    # Substitute {lookback_days} with a concrete integer before passing to HogQL.
    # Agents write this placeholder to parameterize the feature window; we use
    # 4× the horizon as a reasonable lookback (minimum 30 days).
    lookback_days = max(30, pipeline.horizon_days * 4)
    feature_sql = feature_sql.replace("{lookback_days}", str(lookback_days))

    # Append LIMIT directly rather than wrapping in a subquery — HogQL loses
    # the events table context when it sees SELECT * FROM (inner_hogql).
    bounded_sql = feature_sql.rstrip().rstrip(";") + f"\nLIMIT {FEATURE_QUERY_LIMIT}"

    try:
        runner = HogQLQueryRunner(
            query=HogQLQuery(query=bounded_sql),
            team=team,
        )
        result = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)

        if not result.results or not result.columns:
            return []

        columns = result.columns
        return [dict(zip(columns, row)) for row in result.results]

    except Exception:
        logger.exception(
            "autoresearch_feature_query_failed",
            pipeline_id=str(pipeline.pk),
            model_id=str(model.pk),
        )
        return []


def _fetch_label_distinct_ids(
    team: Team,
    pipeline: AutoresearchPipeline,
) -> frozenset[str]:
    """
    Return distinct_ids that performed pipeline.target_event in the last
    horizon_days — used as positive labels when fitting the model.
    """
    label_sql = (
        f"SELECT DISTINCT distinct_id FROM events"
        f" WHERE event = '{pipeline.target_event}'"
        f" AND timestamp >= now() - toIntervalDay({pipeline.horizon_days})"
    )
    try:
        runner = HogQLQueryRunner(query=HogQLQuery(query=label_sql), team=team)
        result = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
        if not result.results:
            return frozenset()
        return frozenset(row[0] for row in result.results if row[0])
    except Exception:
        logger.exception("autoresearch_label_query_failed", pipeline_id=str(pipeline.pk))
        return frozenset()


def _fit_and_score(
    feature_rows: list[dict[str, Any]],
    positive_ids: frozenset[str],
    recipe: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Fit a sklearn classifier on the current feature population with retrospective
    labels, then score every row.

    Label: 1 if the person triggered target_event in the last horizon_days.
    Using the same rows for training and inference is transductive — pragmatic
    for v1 given that the feature SQL isn't parameterized by a cutoff date.

    Falls back to stub scoring when there are too few positives/negatives, when
    the model class can't be resolved, or when fit/predict fails.
    """
    # Identify numeric feature columns (exclude distinct_id and non-numeric values)
    sample = feature_rows[0]
    feature_cols = [
        col for col in sample if col != "distinct_id" and isinstance(sample.get(col), (int, float, type(None)))
    ]

    if not feature_cols:
        logger.warning("autoresearch_no_numeric_features")
        return _score_rows(feature_rows, recipe)

    X = np.array(
        [[float(row.get(col) or 0) for col in feature_cols] for row in feature_rows],
        dtype=np.float64,
    )
    y = np.array(
        [1 if row.get("distinct_id") in positive_ids else 0 for row in feature_rows],
        dtype=np.int32,
    )

    n_pos = int(y.sum())
    n_neg = int(len(y) - n_pos)
    if n_pos < 5 or n_neg < 5:
        logger.warning(
            "autoresearch_insufficient_labels",
            n_pos=n_pos,
            n_neg=n_neg,
        )
        return _score_rows(feature_rows, recipe)

    model_class_path = recipe.get("model_class", "sklearn.linear_model.LogisticRegression")
    model_params = recipe.get("model_params", {})
    try:
        module_path, class_name = model_class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        ModelClass = getattr(module, class_name)
        estimator = ModelClass(**model_params)
        estimator.fit(X, y)
    except Exception:
        logger.exception("autoresearch_model_fit_failed", model_class=model_class_path)
        return _score_rows(feature_rows, recipe)

    try:
        proba = estimator.predict_proba(X)[:, 1]
    except Exception:
        logger.exception("autoresearch_model_predict_failed", model_class=model_class_path)
        return _score_rows(feature_rows, recipe)

    logger.info(
        "autoresearch_sklearn_fit_complete",
        model_class=model_class_path,
        n_train=len(y),
        n_pos=n_pos,
        n_features=len(feature_cols),
    )

    scored = []
    for row, p in zip(feature_rows, proba):
        distinct_id = row.get("distinct_id")
        if not distinct_id:
            continue
        scored.append({**row, "p_y": round(float(p), 4)})
    return scored


def _score_rows(feature_rows: list[dict[str, Any]], recipe: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Apply a scoring function to feature rows.

    For the stub: normalize the total event count into a [0, 1] score
    as a proxy for engagement probability. Real scoring fits a model
    from the recipe's model_class + model_params on historical data.
    """
    if not feature_rows:
        return []

    # Stub scoring: sigmoid of normalised event_count
    # Find the events_total column (name varies by lookback_days in the stub SQL)
    total_col = next(
        (col for col in feature_rows[0].keys() if col.startswith("events_total_") or col == "events_total"),
        None,
    )
    days_col = next(
        (col for col in feature_rows[0].keys() if "days_since_last" in col),
        None,
    )

    def _sigmoid(x: float) -> float:
        return 1.0 / (1.0 + math.exp(-x))

    def _stub_score(row: dict[str, Any]) -> float:
        activity = float(row.get(total_col, 0) or 0) if total_col else 0.0
        recency = float(row.get(days_col, 30) or 30) if days_col else 30.0
        # More activity + more recent → higher score
        raw = (activity / 20.0) - (recency / 14.0)
        return round(_sigmoid(raw), 4)

    scored = []
    for row in feature_rows:
        distinct_id = row.get("distinct_id")
        if not distinct_id:
            continue
        scored.append({**row, "p_y": _stub_score(row)})

    return scored


def _summarize_scores(scores: list[float]) -> dict[str, Any]:
    if not scores:
        return {}
    n = len(scores)
    sorted_scores = sorted(scores)
    return {
        "count": n,
        "mean": round(sum(scores) / n, 4),
        "p10": round(sorted_scores[int(n * 0.10)], 4),
        "p50": round(sorted_scores[int(n * 0.50)], 4),
        "p90": round(sorted_scores[int(n * 0.90)], 4),
        "min": round(sorted_scores[0], 4),
        "max": round(sorted_scores[-1], 4),
    }
