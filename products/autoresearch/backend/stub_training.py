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
            f"Stub recipe for '{pipeline.target_event}' (horizon {pipeline.horizon_days}d, "
            f"{pipeline.prediction_mode} mode). Universal engagement features: event counts, "
            "distinct event types, days since first/last seen."
        ),
        "stub": True,
    }
    recipe["fit_signature"] = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()[:16]
    return recipe


def _recipe_hash(recipe: dict) -> str:
    return hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()


def run_stub_training(
    pipeline: AutoresearchPipeline,
    iteration_budget: int = 1,
) -> AutoresearchTrainingRun:
    """
    Run a single stub training iteration:
    1. Create a TrainingRun record.
    2. Generate the hand-authored recipe.
    3. Create one Iteration (kept) and one AutoresearchModel (champion).
    4. Archive any previous champion.
    5. Mark the pipeline as Running.
    """
    now = django_timezone.now()

    training_run = AutoresearchTrainingRun.objects.create(
        pipeline=pipeline,
        status=AutoresearchTrainingRun.Status.RUNNING,
        iteration_budget=iteration_budget,
        started_at=now,
    )

    try:
        recipe = _build_stub_recipe(pipeline)
        recipe_hash = _recipe_hash(recipe)
        holdout_score = recipe["holdout_score"]

        # Record the single iteration
        AutoresearchIteration.objects.create(
            pipeline=pipeline,
            training_run=training_run,
            iteration_number=1,
            recipe_hash=recipe_hash,
            recipe_snapshot={
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

        # Archive any existing champion
        AutoresearchModel.objects.filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION).update(
            role=AutoresearchModel.Role.ARCHIVED, archived_at=now
        )

        # Persist as new champion
        champion = AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
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
        )

        training_run.iteration_count = 1
        training_run.best_holdout_score = holdout_score
        training_run.status = AutoresearchTrainingRun.Status.COMPLETED
        training_run.completed_at = django_timezone.now()
        training_run.save(update_fields=["iteration_count", "best_holdout_score", "status", "completed_at"])

        pipeline.status = AutoresearchPipeline.Status.RUNNING
        pipeline.iteration_budget_remaining = max(0, pipeline.iteration_budget_remaining - iteration_budget)
        pipeline.save(update_fields=["status", "iteration_budget_remaining", "updated_at"])

        logger.info(
            "autoresearch_stub_training_complete",
            pipeline_id=str(pipeline.pk),
            model_id=str(champion.pk),
            holdout_score=holdout_score,
        )
        return training_run

    except Exception:
        training_run.status = AutoresearchTrainingRun.Status.FAILED
        training_run.completed_at = django_timezone.now()
        training_run.save(update_fields=["status", "completed_at"])
        logger.exception("autoresearch_stub_training_failed", pipeline_id=str(pipeline.pk))
        raise
