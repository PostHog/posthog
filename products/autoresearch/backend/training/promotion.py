"""Champion selection and promotion for agent-recorded training runs.

The agent records candidate iterations; the backend alone decides the champion. Used by
the training-run ``complete`` action and by ``training_ingestion.handle_task_run_completed``
when a run ends without the agent finalizing. When the agent has uploaded a runnable bundle
for the run, the champion's ``artifact_prefix`` points at it (inference runs the bundle in a
sandbox); otherwise the model carries only the recorded recipe (legacy in-process path).
"""

from datetime import date
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import F
from django.utils import timezone as django_timezone

import structlog

from products.autoresearch.backend.inference.sandbox import SandboxInferenceError, fit_champion_model
from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.training import artifacts
from products.autoresearch.backend.training.recipe_validation import RecipeValidationError, validate_feature_sql

logger = structlog.get_logger(__name__)

# A challenger must beat the current champion's holdout score by at least this margin
# before it is promoted — guards against thrashing on noise-level differences.
CHAMPION_PROMOTION_MARGIN = 0.005


class PromotionError(ValueError):
    """Raised when completion cannot select a valid champion candidate."""


def _select_best_iteration(
    training_run: AutoresearchTrainingRun, best_iteration_id: UUID | None
) -> AutoresearchIteration:
    iterations = AutoresearchIteration.objects.filter(training_run=training_run)
    if best_iteration_id is not None and not iterations.filter(id=best_iteration_id).exists():
        raise PromotionError(f"Iteration {best_iteration_id} not found in this training run.")

    # Postgres puts NULLs first on a bare DESC, which would rank an unscored iteration
    # above every scored one.
    ranked_by_score = F("holdout_score").desc(nulls_last=True)
    best = (
        iterations.filter(status=AutoresearchIteration.Status.KEPT, holdout_score__isnull=False)
        .order_by(ranked_by_score)
        .first()
    )
    if best is None:
        # A run whose iterations all crashed, were discarded, or went unscored is a failed
        # experiment. Promoting one of them would install it as a live champion at score 0.
        raise PromotionError("Training run has no kept, scored iteration to select a champion from.")

    if best_iteration_id is not None and best_iteration_id != best.id:
        # The nomination comes from the untrusted sandbox agent, so it can only confirm the
        # server-side ranking, never override it.
        logger.warning(
            "autoresearch_nominated_iteration_not_best",
            training_run_id=str(training_run.id),
            nominated_iteration_id=str(best_iteration_id),
            selected_iteration_id=str(best.id),
        )
    return best


def _build_recipe(iteration: AutoresearchIteration) -> dict[str, Any]:
    snapshot = iteration.recipe_snapshot or {}
    spec = iteration.model_spec or {}
    return {
        "feature_sql": snapshot.get("feature_sql", ""),
        "feature_transforms": snapshot.get("feature_transforms", []),
        "model_class": spec.get("model_class", "sklearn.linear_model.LogisticRegression"),
        "model_params": spec.get("model_params", {}),
        "fit_signature": (iteration.recipe_hash or "")[:16],
        "trained_on": date.today().isoformat(),
        "holdout_score": iteration.holdout_score or 0.0,
        "agent_description": iteration.agent_description,
    }


def _summary_item(iteration: AutoresearchIteration) -> dict[str, Any]:
    spec = iteration.model_spec or {}
    return {
        "iteration_number": iteration.iteration_number,
        "holdout_score": iteration.holdout_score,
        "model_class": spec.get("model_class", ""),
        "agent_description": iteration.agent_description or "",
    }


def _build_run_summary(
    training_run: AutoresearchTrainingRun,
    *,
    best: AutoresearchIteration | None,
    iterations: list[AutoresearchIteration],
    promoted: bool,
    recommended_next: str,
    distillation: str,
) -> dict[str, Any]:
    """Tier-1 cross-run memory: backend derives the structural facts; the agent supplies the two
    judgment fields (recommended_next, distillation). Read back by a new run before it iterates."""
    pipeline = training_run.pipeline
    kept = sorted(
        (it for it in iterations if it.status == AutoresearchIteration.Status.KEPT),
        key=lambda it: it.holdout_score if it.holdout_score is not None else -1.0,
        reverse=True,
    )
    dead_ends = [it for it in iterations if it.status != AutoresearchIteration.Status.KEPT]
    best_spec = (best.model_spec or {}) if best else {}
    return {
        "target_event": pipeline.target_event,
        "horizon_days": pipeline.horizon_days,
        "best_holdout_score": best.holdout_score if best else None,
        "champion_promoted": promoted,
        "champion_model_class": best_spec.get("model_class", ""),
        "kept_ladder": [_summary_item(it) for it in kept],
        "dead_ends": [_summary_item(it) for it in dead_ends],
        "recommended_next": recommended_next or "",
        "distillation": distillation or "",
    }


def _detect_uploaded_bundle(training_run: AutoresearchTrainingRun) -> str | None:
    """
    If the agent uploaded a complete artifact bundle (train.py, predict.py, features.sql)
    for this run, return its object-storage prefix. Returns None when no complete bundle is
    present (the legacy recipe-only path).

    Only ``BundleNotFound`` means "no bundle". Any other storage failure propagates and
    aborts completion so it can be retried — swallowing it would permanently pin the model
    to the legacy recipe path on a transient storage blip.
    """
    pipeline = training_run.pipeline
    prefix = artifacts.bundle_prefix(
        team_id=pipeline.team_id,
        pipeline_id=str(training_run.pipeline_id),
        training_run_id=str(training_run.id),
    )
    try:
        bundle = artifacts.read_bundle(prefix)
    except artifacts.BundleNotFound:
        return None
    except Exception:
        logger.exception("autoresearch_bundle_read_failed", training_run_id=str(training_run.id), prefix=prefix)
        raise
    # The uploaded features.sql is what fitting and scoring actually execute, and the agent
    # can upload SQL that never went through iteration recording — validate the real file.
    try:
        validate_feature_sql(bundle.features_sql)
    except RecipeValidationError as exc:
        raise PromotionError(f"Uploaded bundle's features.sql failed validation: {exc}") from exc
    return prefix


@transaction.atomic
def complete_training_run(
    training_run: AutoresearchTrainingRun,
    *,
    best_iteration_id: UUID | None = None,
    model_explanation: dict[str, Any] | None = None,
    recommended_next: str = "",
    distillation: str = "",
) -> dict[str, Any]:
    """Finalize a run: pick the best iteration, decide champion vs challenger, persist the model."""
    # Re-fetch under lock and re-check status inside the transaction. Both callers (the
    # complete API action and the TaskRun post_save safety net) guard on status outside
    # it, so a retry racing the signal could otherwise finalize the same run twice —
    # duplicate champion/challenger rows and duplicate on_commit fits.
    training_run = (
        AutoresearchTrainingRun.objects.select_for_update().select_related("pipeline").get(pk=training_run.pk)
    )
    if training_run.status not in (
        AutoresearchTrainingRun.Status.RUNNING,
        AutoresearchTrainingRun.Status.PENDING,
    ):
        logger.info(
            "autoresearch_training_run_already_finalized",
            training_run_id=str(training_run.id),
            status=training_run.status,
        )
        return {
            "promoted": False,
            "model_id": None,
            "role": None,
            "iteration_count": training_run.iteration_count,
            "best_holdout_score": training_run.best_holdout_score,
        }

    pipeline = training_run.pipeline
    now = django_timezone.now()

    iterations = list(AutoresearchIteration.objects.filter(training_run=training_run))
    iteration_count = len(iterations)
    if not iterations:
        # Mirrors the "Agent recorded no iterations before the run ended." failure the
        # TaskRun safety net produces — completing here would leave a BOOTSTRAPPING
        # pipeline with no champion and no retry.
        raise PromotionError("Agent recorded no iterations, so there is nothing to complete.")

    best = _select_best_iteration(training_run, best_iteration_id)

    # If the agent uploaded a runnable bundle, the champion's artifact is that bundle
    # (inference runs train.py/predict.py in a sandbox).
    artifact_prefix = _detect_uploaded_bundle(training_run) or ""
    best_feature_sql = str((best.recipe_snapshot or {}).get("feature_sql") or "")
    if not artifact_prefix and not best_feature_sql.strip():
        # Without a bundle the model takes the legacy in-process path, which scores by
        # running the recorded feature_sql — an empty one would produce an unusable champion.
        raise PromotionError(
            "Cannot persist a model: no complete bundle was uploaded and the selected "
            "iteration recorded no feature_sql for the legacy scoring path."
        )

    best_score = best.holdout_score
    candidate_score = best.holdout_score or 0.0
    current = AutoresearchModel.objects.filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION).first()
    is_cold_start = current is None
    beats_champion = (
        current is not None and candidate_score >= (current.holdout_score or 0.0) + CHAMPION_PROMOTION_MARGIN
    )

    promoted = False
    role: str
    if is_cold_start or beats_champion:
        if current is not None:
            AutoresearchModel.objects.filter(pk=current.pk).update(
                role=AutoresearchModel.Role.ARCHIVED, archived_at=now
            )
        role = AutoresearchModel.Role.CHAMPION
        promoted = True
    else:
        role = AutoresearchModel.Role.CHALLENGER

    # The recipe JSON (derived from the winning iteration's model_spec/snapshot) backs the
    # legacy in-process path and the model card.
    model_recipe = _build_recipe(best)
    model = AutoresearchModel.objects.create(
        pipeline=pipeline,
        role=role,
        recipe_hash=best.recipe_hash or "",
        model_recipe=model_recipe,
        artifact_prefix=artifact_prefix,
        model_explanation=model_explanation or {},
        holdout_score=candidate_score,
        metrics={
            "holdout_auc": candidate_score,
            "source": "agent_recorded",
            "artifact_bundle": bool(artifact_prefix),
        },
        source_training_run=training_run,
        agent_description=best.agent_description,
        trained_on_start=date.today(),
        trained_on_end=date.today(),
        is_preliminary=True,
        promoted_at=now if promoted else None,
    )

    training_run.status = AutoresearchTrainingRun.Status.COMPLETED
    training_run.iteration_count = iteration_count
    training_run.best_holdout_score = best_score
    training_run.completed_at = now
    training_run.summary = _build_run_summary(
        training_run,
        best=best,
        iterations=iterations,
        promoted=promoted,
        recommended_next=recommended_next,
        distillation=distillation,
    )
    training_run.save(update_fields=["status", "iteration_count", "best_holdout_score", "summary", "completed_at"])

    # A pipeline with its first champion goes live: flip Draft/Bootstrapping -> Running so the
    # daily coordinator starts scoring it. Mirrors the stub path (stub_training); pause/resume
    # handle the rest. Guarded on the pre-live statuses so re-promotions on an already-live
    # (Running/Converged/Paused) pipeline are no-ops.
    if promoted and pipeline.status in (
        AutoresearchPipeline.Status.DRAFT,
        AutoresearchPipeline.Status.BOOTSTRAPPING,
    ):
        pipeline.status = AutoresearchPipeline.Status.RUNNING
        pipeline.save(update_fields=["status", "updated_at"])

    # The train run produces the serving artifact: fit the champion and persist model.pkl
    # so predict runs are pure inference. Deferred to on_commit — the sandbox + object-storage
    # write are side effects that must not run inside this atomic block, and we only fit once
    # the row is durably committed. A failure here is non-fatal: the predict run self-heals by
    # fitting on first score.
    if artifact_prefix:
        captured_pipeline = pipeline
        captured_prefix = artifact_prefix
        captured_run_id = str(training_run.id)

        def _fit_champion_after_commit() -> None:
            try:
                fit_champion_model(team=captured_pipeline.team, pipeline=captured_pipeline, prefix=captured_prefix)
            except SandboxInferenceError:
                logger.exception(
                    "autoresearch_champion_fit_failed", training_run_id=captured_run_id, prefix=captured_prefix
                )

        transaction.on_commit(_fit_champion_after_commit)

    return {
        "promoted": promoted,
        "model_id": str(model.pk),
        "role": role,
        "iteration_count": iteration_count,
        "best_holdout_score": best_score,
    }
