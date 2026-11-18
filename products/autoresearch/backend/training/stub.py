"""
Stub training: produces a hand-authored champion recipe without running the
actual autoresearch agent loop. Used for local dev and E2E testing until the
real sandboxed training harness is wired up.

The stub recipe uses universal engagement features that apply to any team and
any target event: event counts, distinct event types, and days since first seen.
These compile to HogQL at inference time via the recipe compiler in inference.py.
"""

import json
import hashlib
from datetime import date

from django.db import transaction
from django.utils import timezone as django_timezone

import structlog

from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchTrainingRun,
)

logger = structlog.get_logger(__name__)

# Universal feature SQL template — compiled against the inference population at scoring time.
# The {lookback_days} placeholder is filled from the pipeline's horizon_days * 4.
# autoresearch_* events are the model's own output — counting them would feed each scoring
# cadence's predictions back into the next one's features.
STUB_FEATURE_SQL_TEMPLATE = """
SELECT
    person_id AS distinct_id,
    countIf(timestamp >= now() - toIntervalDay({lookback_days})) AS events_total_{lookback_days}d,
    uniqIf(event, timestamp >= now() - toIntervalDay({lookback_days})) AS distinct_event_types_{lookback_days}d,
    countIf(event = '$pageview' AND timestamp >= now() - toIntervalDay({lookback_days})) AS pageviews_{lookback_days}d,
    countIf(event = '$pageleave' AND timestamp >= now() - toIntervalDay({lookback_days})) AS pageleaves_{lookback_days}d,
    countIf(timestamp >= now() - toIntervalDay(7)) AS events_last_7d,
    dateDiff('day', min(timestamp), now()) AS days_since_first_seen,
    dateDiff('day', max(timestamp), now()) AS days_since_last_seen
FROM events
WHERE person_id IS NOT NULL
  AND timestamp >= now() - toIntervalDay({max_lookback})
  AND timestamp < now()
  AND NOT startsWith(event, 'autoresearch_')
GROUP BY person_id
""".strip()


def _build_stub_recipe(pipeline: AutoresearchPipeline) -> dict:
    lookback_days = max(pipeline.horizon_days * 4, 30)
    feature_sql = STUB_FEATURE_SQL_TEMPLATE.format(
        lookback_days=lookback_days,
        max_lookback=lookback_days * 2,
    )
    recipe = {
        "feature_sql": feature_sql,
        "feature_transforms": [],
        "model_class": "sklearn.linear_model.LogisticRegression",
        "model_params": {"C": 1.0, "max_iter": 200, "class_weight": "balanced"},
        "fit_signature": "",
        "trained_on": f"{date.today().isoformat()} (stub)",
        "holdout_score": 0.70,
        "agent_description": (
            f"Stub recipe for '{pipeline.target_event}' (horizon {pipeline.horizon_days}d). "
            "Universal engagement features: event counts, distinct event types, days since first/last seen."
        ),
        "stub": True,
    }
    recipe["fit_signature"] = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()[:16]
    return recipe


def _recipe_hash(recipe: dict) -> str:
    return hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()


def _record_stub_result(
    pipeline: AutoresearchPipeline, training_run: AutoresearchTrainingRun, iteration_budget: int
) -> AutoresearchModel:
    # Lock the pipeline so concurrent stub runs debit the budget and move the status one at a time.
    locked = AutoresearchPipeline.objects.select_for_update().get(pk=pipeline.pk)
    recipe = _build_stub_recipe(locked)
    recipe_hash = _recipe_hash(recipe)
    holdout_score = recipe["holdout_score"]
    now = django_timezone.now()

    AutoresearchIteration.objects.create(
        pipeline=pipeline,
        training_run=training_run,
        iteration_number=1,
        recipe_hash=recipe_hash,
        recipe_snapshot={
            "feature_sql": recipe["feature_sql"],
            "feature_transforms": recipe["feature_transforms"],
            "model_class": recipe["model_class"],
            "model_params": recipe["model_params"],
            "holdout_score": holdout_score,
        },
        model_spec={
            "model_class": recipe["model_class"],
            "model_params": recipe["model_params"],
        },
        train_score=holdout_score,
        holdout_score=holdout_score,
        status=AutoresearchIteration.Status.KEPT,
        agent_description=recipe["agent_description"],
        agent_confidence=0.5,
    )

    # A stub replaces an earlier stub freely, so local runs can repeat. Its score is a
    # placeholder, not a measurement, so it never replaces a trained champion.
    incumbent = (
        AutoresearchModel.objects.select_for_update()
        .filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
        .first()
    )
    promote = incumbent is None or bool((incumbent.metrics or {}).get("stub"))
    if promote and incumbent is not None:
        incumbent.role = AutoresearchModel.Role.ARCHIVED
        incumbent.archived_at = now
        incumbent.save(update_fields=["role", "archived_at"])

    model = AutoresearchModel.objects.create(
        pipeline=pipeline,
        role=AutoresearchModel.Role.CHAMPION if promote else AutoresearchModel.Role.CHALLENGER,
        recipe_hash=recipe_hash,
        model_recipe=recipe,
        model_explanation={
            "top_features": [
                {"name": "events_total", "importance": 0.35, "direction": "positive"},
                {"name": "days_since_last_seen", "importance": 0.28, "direction": "negative"},
                {"name": "distinct_event_types", "importance": 0.20, "direction": "positive"},
                {"name": "pageviews", "importance": 0.17, "direction": "positive"},
            ],
            "note": "Stub explanations — replace with real SHAP values once training is live.",
        },
        holdout_score=holdout_score,
        metrics={"holdout_auc": holdout_score, "stub": True},
        source_training_run=training_run,
        agent_description=recipe["agent_description"],
        trained_on_start=date.today(),
        trained_on_end=date.today(),
        is_preliminary=True,
        promoted_at=now if promote else None,
    )

    training_run.iteration_count = 1
    training_run.best_holdout_score = holdout_score
    training_run.status = AutoresearchTrainingRun.Status.COMPLETED
    training_run.completed_at = django_timezone.now()
    training_run.save(update_fields=["iteration_count", "best_holdout_score", "status", "completed_at"])

    update_fields = ["iteration_budget_remaining", "updated_at"]
    # Only a pipeline with no live champion yet starts running; a paused or archived one stays as it is.
    if promote and locked.status in (AutoresearchPipeline.Status.DRAFT, AutoresearchPipeline.Status.BOOTSTRAPPING):
        locked.status = AutoresearchPipeline.Status.RUNNING
        update_fields.append("status")
    locked.iteration_budget_remaining = max(0, (locked.iteration_budget_remaining or 0) - iteration_budget)
    locked.save(update_fields=update_fields)
    pipeline.refresh_from_db(fields=["status", "iteration_budget_remaining", "updated_at"])
    return model


def run_stub_training(
    pipeline: AutoresearchPipeline,
    iteration_budget: int = 1,
) -> AutoresearchTrainingRun:
    """
    Run a single stub training iteration:
    1. Create a TrainingRun record.
    2. Generate the hand-authored recipe.
    3. Create one Iteration (kept) and one AutoresearchModel.
    4. Make it champion unless the pipeline already has a trained champion.
    5. Mark a Draft or Bootstrapping pipeline as Running.
    """
    training_run = AutoresearchTrainingRun.objects.create(
        pipeline=pipeline,
        status=AutoresearchTrainingRun.Status.RUNNING,
        iteration_budget=iteration_budget,
        started_at=django_timezone.now(),
    )

    try:
        with transaction.atomic():
            model = _record_stub_result(pipeline, training_run, iteration_budget)
        logger.info(
            "autoresearch_stub_training_complete",
            pipeline_id=str(pipeline.pk),
            model_id=str(model.pk),
            role=model.role,
        )
        return training_run

    except Exception as e:
        training_run.status = AutoresearchTrainingRun.Status.FAILED
        training_run.completed_at = django_timezone.now()
        training_run.error = str(e)[:2000]
        training_run.save(update_fields=["status", "completed_at", "error"])
        logger.exception("autoresearch_stub_training_failed", pipeline_id=str(pipeline.pk))
        raise
