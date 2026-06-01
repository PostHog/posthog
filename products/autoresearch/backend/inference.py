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
from datetime import UTC, date, datetime
from typing import Any

from django.utils import timezone as django_timezone

import numpy as np
import structlog

from posthog.schema import HogQLQuery

from posthog.api.capture import capture_internal
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team.team import Team

from products.autoresearch.backend.labeling import (
    _build_population_conditions,
    build_inference_features_sql,
    build_training_features_sql,
)
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline, AutoresearchRun
from products.autoresearch.backend.recipe_validation import validate_model_class
from products.autoresearch.backend.sandbox_inference import score_via_sandbox

logger = structlog.get_logger(__name__)

EVENT_SOURCE = "autoresearch_inference"
PREDICTION_EVENT_NAME = "autoresearch_prediction"

# Batch size for ClickHouse feature queries — keeps memory bounded
FEATURE_QUERY_LIMIT = 10_000

# Anchors-style feature SQL contract marker (see labeling.py + Step B validator).
# Presence routes through _score_via_anchors; absence falls back to the legacy
# transductive path for older recipes.
_ANCHORS_PLACEHOLDER = "{anchors}"

# Internal columns added by labeling.build_training_features_sql.
_LABEL_COL = "__label"
_FOLD_COL = "__fold"
# Reserve fold == 0 as the holdout slice; folds 1..N-1 are training.
_HOLDOUT_FOLD = 0


def run_inference_for_pipeline(
    pipeline: AutoresearchPipeline,
    model: AutoresearchModel,
    prediction_date: date | None = None,
) -> AutoresearchRun:
    """
    Top-level inference entry point. Creates an AutoresearchRun, scores users,
    emits prediction events, and records metrics.

    ``prediction_date`` defaults to today (live daily scoring). Pass a past date
    to backfill: features are computed as-of that date and prediction events are
    emitted with that date's timestamp, so online validation can score it once
    the horizon has elapsed instead of waiting for real time to pass.

    Called by:
    - AutoresearchPipelineViewSet.run_inference (API)
    - autoresearch_score management command
    - AutoresearchInferenceWorkflow Temporal activity
    """
    prediction_date = prediction_date or date.today()
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
        rows_scored, score_distribution, holdout_auc = _score_and_emit(
            team=team,
            pipeline=pipeline,
            model=model,
            prediction_date=prediction_date,
        )

        run.status = AutoresearchRun.Status.COMPLETED
        run.rows_scored = rows_scored
        run.metrics = {
            "score_distribution": score_distribution,
            "stub": (model.model_recipe or {}).get("stub", False),
            "sandbox": bool(model.artifact_prefix),
            "holdout_auc": holdout_auc,
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

    except Exception as exc:
        run.status = AutoresearchRun.Status.FAILED
        run.error = str(exc)[:2000]
        run.completed_at = django_timezone.now()
        run.save(update_fields=["status", "error", "completed_at"])
        logger.exception("autoresearch_inference_failed", pipeline_id=str(pipeline.pk))
        raise


def _score_and_emit(
    team: Team,
    pipeline: AutoresearchPipeline,
    model: AutoresearchModel,
    prediction_date: date,
) -> tuple[int, dict[str, Any], float | None]:
    """
    Fetch feature rows, compute scores, emit prediction events.
    Returns (rows_scored, score_distribution_summary, holdout_auc).
    """
    holdout_auc: float | None = None

    # Backfill vs live: a past prediction_date computes features as-of that day's
    # start (leak-free, mirrors the labeler's T0 contract) and stamps the emitted
    # events at that date so they land in the right window for online validation.
    is_backfill = prediction_date < date.today()
    cutoff_ts = (
        int(datetime(prediction_date.year, prediction_date.month, prediction_date.day, tzinfo=UTC).timestamp())
        if is_backfill
        else None
    )

    # Artifact-bundle models run fit + predict in a sandbox and fully own scoring;
    # this bypasses both the anchors and legacy in-process paths. Failures raise
    # (no stub fallback) so the run fails loudly rather than emitting noise.
    if model.artifact_prefix:
        result = score_via_sandbox(team=team, pipeline=pipeline, model=model, cutoff_ts=cutoff_ts)
        scored = result.scored_rows
        holdout_auc = result.holdout_auc
    else:
        recipe = model.model_recipe or {}
        feature_sql = recipe.get("feature_sql", "")

        # Route based on the recipe contract. New anchors-style recipes get the
        # leak-free path: features and labels both live in time strictly before
        # each user's cutoff_ts, training cohort != scoring cohort, fit happens
        # on training-fold rows only. Legacy recipes fall through to the
        # transductive path until they're regenerated.
        if _ANCHORS_PLACEHOLDER in feature_sql:
            scored = _score_via_anchors(team=team, pipeline=pipeline, recipe=recipe)
        else:
            feature_rows = _fetch_feature_rows(team=team, pipeline=pipeline, model=model)
            if not feature_rows:
                logger.warning(
                    "autoresearch_no_feature_rows",
                    pipeline_id=str(pipeline.pk),
                    team_id=team.pk,
                )
                return 0, {}, holdout_auc
            if recipe.get("stub"):
                scored = _score_rows(feature_rows=feature_rows, recipe=recipe)
            else:
                positive_ids = _fetch_label_distinct_ids(team=team, pipeline=pipeline)
                scored = _fit_and_score(feature_rows=feature_rows, positive_ids=positive_ids, recipe=recipe)

    if not scored:
        logger.warning(
            "autoresearch_no_scored_rows",
            pipeline_id=str(pipeline.pk),
            team_id=team.pk,
        )
        return 0, {}, holdout_auc

    scores = [s["p_y"] for s in scored]
    score_distribution = _summarize_scores(scores)

    token = team.api_token
    prediction_date_str = prediction_date.isoformat()
    # Live runs stamp now(); backfills stamp the prediction date (noon UTC) so the
    # events land in that day's window rather than today's.
    emit_timestamp = (
        datetime(prediction_date.year, prediction_date.month, prediction_date.day, 12, tzinfo=UTC)
        if is_backfill
        else django_timezone.now()
    )

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
                timestamp=emit_timestamp,
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

    return emitted, score_distribution, holdout_auc


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
        tag_queries(product=Product.AUTORESEARCH, feature=Feature.QUERY)
        runner = HogQLQueryRunner(
            query=HogQLQuery(query=bounded_sql),
            team=team,
        )
        result = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)

        if not result.results or not result.columns:
            return []

        columns = result.columns
        rows = [dict(zip(columns, row)) for row in result.results]
        # Feature SQL keys rows on person_id (a UUID); coerce to str so the value is
        # JSON-serializable for event emission and matches the str-keyed label set.
        for r in rows:
            if r.get("distinct_id") is not None:
                r["distinct_id"] = str(r["distinct_id"])

    except Exception:
        logger.exception(
            "autoresearch_feature_query_failed",
            pipeline_id=str(pipeline.pk),
            model_id=str(model.pk),
        )
        return []

    # Apply inference population filter — restrict to users matching the pipeline's
    # defined scoring population (e.g. identified users, signed up in last 30 days).
    # Skip the population query entirely when no filter is defined (empty dict = all users).
    allowed_ids: frozenset[str] | None = None
    if pipeline.inference_population:
        lookback_days = max(30, pipeline.horizon_days * 4)
        allowed_ids = _fetch_population_distinct_ids(
            team=team,
            population=pipeline.inference_population,
            lookback_days=lookback_days,
        )
    if allowed_ids is not None:
        before = len(rows)
        rows = [r for r in rows if r.get("distinct_id") in allowed_ids]
        logger.info(
            "autoresearch_population_filter_applied",
            pipeline_id=str(pipeline.pk),
            before=before,
            after=len(rows),
        )

    return rows


def _fetch_population_distinct_ids(
    team: Team,
    population: dict[str, Any],
    lookback_days: int,
) -> frozenset[str] | None:
    """
    Return the set of distinct_ids that match the inference_population filter.
    Returns None when no filter applies (empty dict = score all users).

    Queries the events table using person property conditions so the eligible set
    is consistent with the feature SQL lookback window — users with no recent
    events have no feature rows and wouldn't be scored anyway.

    On query failure, returns None (fail open) rather than silently scoring zero.

    Supports person and event property types with common operators (exact, is_not,
    icontains, not_icontains, gt/gte/lt/lte, is_set, is_not_set).
    """
    if not population:
        return None

    properties = population.get("properties", [])
    if not properties:
        return None

    parts, values = _build_population_conditions(properties)
    if not parts:
        return None

    values["_lookback"] = lookback_days
    where_clause = " AND ".join(parts)
    sql = (
        f"SELECT DISTINCT person_id FROM events"
        f" WHERE timestamp >= now() - toIntervalDay({{_lookback}})"
        f" AND {where_clause}"
    )

    try:
        tag_queries(product=Product.AUTORESEARCH, feature=Feature.QUERY)
        runner = HogQLQueryRunner(query=HogQLQuery(query=sql, values=values), team=team)
        result = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
        if not result.results:
            return frozenset()
        return frozenset(str(row[0]) for row in result.results if row[0])
    except Exception:
        logger.exception("autoresearch_population_query_failed", team_id=team.pk)
        return None


def _fetch_label_distinct_ids(
    team: Team,
    pipeline: AutoresearchPipeline,
) -> frozenset[str]:
    """
    Return distinct_ids that performed pipeline.target_event in the last
    horizon_days — used as positive labels when fitting the model.
    """
    # Key on person_id to match the feature SQL (one row per person_id); feature rows
    # are str(person_id), so labels must be str(person_id) too or nothing matches.
    label_sql = (
        f"SELECT DISTINCT person_id FROM events"
        f" WHERE event = '{pipeline.target_event}'"
        f" AND timestamp >= now() - toIntervalDay({pipeline.horizon_days})"
    )
    try:
        tag_queries(product=Product.AUTORESEARCH, feature=Feature.QUERY)
        runner = HogQLQueryRunner(query=HogQLQuery(query=label_sql), team=team)
        result = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
        if not result.results:
            return frozenset()
        return frozenset(str(row[0]) for row in result.results if row[0])
    except Exception:
        logger.exception("autoresearch_label_query_failed", pipeline_id=str(pipeline.pk))
        return frozenset()


def _score_via_anchors(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    recipe: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Anchors-style scoring (the leak-free path).

    The agent's feature_sql contains `{anchors}` and reads events with
    `e.timestamp < fromUnixTimestamp(a.cutoff_ts)`. Same SQL runs against two
    different anchor tables:
      - training anchors: per-user random T0 + labels + fold (from labeling.py)
      - inference anchors: (person_id, cutoff_ts = now()) for users to score

    We fit on training rows where fold != 0, evaluate on fold == 0 for a
    real holdout AUC, then predict on the inference rows. Falls back to stub
    scoring if anything in the train path fails — that lets a half-broken
    recipe still emit (zero-information) predictions instead of nothing.
    """
    feature_sql = recipe.get("feature_sql", "")
    if not feature_sql:
        logger.warning("autoresearch_empty_feature_sql", pipeline_id=str(pipeline.pk))
        return []

    # Substitute {lookback_days} consistently — same value at train and inference
    # so the feature window has the same width in both phases.
    lookback_days = max(30, pipeline.horizon_days * 4)
    feature_sql_resolved = feature_sql.replace("{lookback_days}", str(lookback_days))

    training_rows = _fetch_training_rows(team=team, pipeline=pipeline, feature_sql=feature_sql_resolved)
    inference_rows = _fetch_inference_rows(team=team, pipeline=pipeline, feature_sql=feature_sql_resolved)
    if not inference_rows:
        logger.warning(
            "autoresearch_no_inference_rows",
            pipeline_id=str(pipeline.pk),
        )
        return []
    if not training_rows:
        logger.warning(
            "autoresearch_no_training_rows_anchored_fallback_stub",
            pipeline_id=str(pipeline.pk),
        )
        return _score_rows(inference_rows, recipe)

    return _fit_on_training_predict_on_inference(
        training_rows=training_rows,
        inference_rows=inference_rows,
        recipe=recipe,
        pipeline_id=str(pipeline.pk),
    )


def _fetch_training_rows(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    feature_sql: str,
) -> list[dict[str, Any]]:
    """
    Run the composite training-features SQL: build the labeled_anchors CTE
    from the random-T0 labeler, substitute it into the agent's feature_sql,
    JOIN back to bring __label + __fold onto each row. One row per eligible
    user.
    """
    sql, values = build_training_features_sql(
        feature_sql=feature_sql,
        target_event=pipeline.target_event,
        horizon_days=pipeline.horizon_days,
        lookback_days=pipeline.training_lookback_days,
        training_population=pipeline.training_population,
    )
    try:
        tag_queries(product=Product.AUTORESEARCH, feature=Feature.QUERY)
        runner = HogQLQueryRunner(query=HogQLQuery(query=sql, values=values), team=team)
        result = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
        if not result.results or not result.columns:
            return []
        columns = result.columns
        rows = [dict(zip(columns, row)) for row in result.results]
        for r in rows:
            if r.get("distinct_id") is not None:
                r["distinct_id"] = str(r["distinct_id"])
        return rows
    except Exception:
        logger.exception(
            "autoresearch_training_features_query_failed",
            pipeline_id=str(pipeline.pk),
        )
        return []


def _fetch_inference_rows(
    *,
    team: Team,
    pipeline: AutoresearchPipeline,
    feature_sql: str,
) -> list[dict[str, Any]]:
    """
    Run the inference-features SQL: substitute {anchors} in the agent's
    feature_sql with the inference anchors (cutoff_ts = now() per user).
    Returns one row per eligible scoring user, no labels.
    """
    lookback_days = max(30, pipeline.horizon_days * 4)
    sql, values = build_inference_features_sql(
        feature_sql=feature_sql,
        lookback_days=lookback_days,
        inference_population=pipeline.inference_population,
    )
    try:
        tag_queries(product=Product.AUTORESEARCH, feature=Feature.QUERY)
        runner = HogQLQueryRunner(query=HogQLQuery(query=sql, values=values), team=team)
        result = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
        if not result.results or not result.columns:
            return []
        columns = result.columns
        rows = [dict(zip(columns, row)) for row in result.results]
        for r in rows:
            if r.get("distinct_id") is not None:
                r["distinct_id"] = str(r["distinct_id"])
        return rows
    except Exception:
        logger.exception(
            "autoresearch_inference_features_query_failed",
            pipeline_id=str(pipeline.pk),
        )
        return []


def _fit_on_training_predict_on_inference(
    *,
    training_rows: list[dict[str, Any]],
    inference_rows: list[dict[str, Any]],
    recipe: dict[str, Any],
    pipeline_id: str,
) -> list[dict[str, Any]]:
    """
    Fit the recipe's sklearn model on training rows (fold != 0), evaluate on
    the holdout slice (fold == 0) for a real holdout AUC, predict on
    inference rows. Falls back to stub scoring on any failure so we still
    emit predictions (zero-information rather than nothing).
    """
    feature_cols = sorted(
        col
        for col in training_rows[0]
        if col not in {"distinct_id", _LABEL_COL, _FOLD_COL}
        and isinstance(training_rows[0].get(col), (int, float, type(None)))
    )
    if not feature_cols:
        logger.warning("autoresearch_no_numeric_features", pipeline_id=pipeline_id)
        return _score_rows(inference_rows, recipe)

    train_rows = [r for r in training_rows if (r.get(_FOLD_COL) or 0) != _HOLDOUT_FOLD]
    holdout_rows = [r for r in training_rows if (r.get(_FOLD_COL) or 0) == _HOLDOUT_FOLD]

    if not train_rows:
        logger.warning("autoresearch_no_train_fold_rows", pipeline_id=pipeline_id)
        return _score_rows(inference_rows, recipe)

    X_train = np.array(
        [[float(r.get(c) or 0) for c in feature_cols] for r in train_rows],
        dtype=np.float64,
    )
    y_train = np.array(
        [int(r.get(_LABEL_COL) or 0) for r in train_rows],
        dtype=np.int32,
    )
    n_pos = int(y_train.sum())
    n_neg = int(len(y_train) - n_pos)
    if n_pos < 5 or n_neg < 5:
        logger.warning(
            "autoresearch_insufficient_labels",
            pipeline_id=pipeline_id,
            n_pos=n_pos,
            n_neg=n_neg,
        )
        return _score_rows(inference_rows, recipe)

    model_class_path = recipe.get("model_class", "sklearn.linear_model.LogisticRegression")
    model_params = recipe.get("model_params", {})
    try:
        # This is the in-process legacy path: model_class is resolved via importlib,
        # an arbitrary-code surface. Gate it on the allowlist here, at the execution
        # point (iteration recording no longer does — the agent's real model runs in
        # the sandboxed bundle, where any class is fine).
        validate_model_class(model_class_path)
        module_path, class_name = model_class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        ModelClass = getattr(module, class_name)
        estimator = ModelClass(**model_params)
        estimator.fit(X_train, y_train)
    except Exception:
        logger.exception(
            "autoresearch_anchored_fit_failed",
            pipeline_id=pipeline_id,
            model_class=model_class_path,
        )
        return _score_rows(inference_rows, recipe)

    # Holdout AUC — informational. Logged so we can see the realized vs
    # claimed AUC gap later. Skip silently if holdout is empty or single-class.
    if holdout_rows:
        try:
            from sklearn.metrics import roc_auc_score

            X_holdout = np.array(
                [[float(r.get(c) or 0) for c in feature_cols] for r in holdout_rows],
                dtype=np.float64,
            )
            y_holdout = np.array(
                [int(r.get(_LABEL_COL) or 0) for r in holdout_rows],
                dtype=np.int32,
            )
            if len(set(y_holdout.tolist())) > 1:
                p_holdout = estimator.predict_proba(X_holdout)[:, 1]
                holdout_auc = float(roc_auc_score(y_holdout, p_holdout))
                logger.info(
                    "autoresearch_anchored_holdout_auc",
                    pipeline_id=pipeline_id,
                    holdout_auc=round(holdout_auc, 4),
                    n_train=len(y_train),
                    n_holdout=len(y_holdout),
                    n_features=len(feature_cols),
                )
        except Exception:
            logger.exception("autoresearch_holdout_auc_failed", pipeline_id=pipeline_id)

    # Score inference rows
    try:
        X_score = np.array(
            [[float(r.get(c) or 0) for c in feature_cols] for r in inference_rows],
            dtype=np.float64,
        )
        proba = estimator.predict_proba(X_score)[:, 1]
    except Exception:
        logger.exception(
            "autoresearch_anchored_predict_failed",
            pipeline_id=pipeline_id,
            model_class=model_class_path,
        )
        return _score_rows(inference_rows, recipe)

    scored: list[dict[str, Any]] = []
    for row, p in zip(inference_rows, proba):
        distinct_id = row.get("distinct_id")
        if not distinct_id:
            continue
        scored.append({**row, "p_y": round(float(p), 4)})
    return scored


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
        # Legacy in-process path — gate the importlib resolution on the allowlist
        # (see the matching guard in _score_via_anchors).
        validate_model_class(model_class_path)
        module_path, class_name = model_class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        ModelClass = getattr(module, class_name)
        estimator = ModelClass(**model_params)
        estimator.fit(X, y)
    except Exception:
        logger.exception("autoresearch_model_fit_failed", model_class=model_class_path)
        return _score_rows(feature_rows, recipe)

    try:
        # Binary classification: column 1 is P(y=1). Multi-class would need
        # a different event shape (one $autoresearch_p_<class> per column).
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
