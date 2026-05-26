"""
Training result ingestion: processes a completed TaskRun and materialises the
agent's recipe into an AutoresearchModel + AutoresearchIteration records.

Entry points:
  - handle_task_run_completed(task_run): called from the TaskRun post_save signal
    registered in apps.py. Runs synchronously in the Temporal worker thread.
    Fast path (structured output): only DB writes, ~few ms.
    Slow path (S3 log fallback): one S3 read + JSON extraction.
"""

from __future__ import annotations

import re
import json
import hashlib
from datetime import date
from typing import Any

from django.utils import timezone as django_timezone

import structlog
from pydantic import ValidationError

from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.training import ModelRecipeOutput

logger = structlog.get_logger(__name__)


# ── Public entry point ─────────────────────────────────────────────────────────


def handle_task_run_completed(task_run: Any) -> None:
    """
    Process a completed (or failed/cancelled) TaskRun for an autoresearch pipeline.

    Called from the post_save signal in apps.py. Safe to call multiple times —
    the training_run status check prevents double-ingestion.
    """
    training_run_id = (task_run.state or {}).get("autoresearch_training_run_id")
    if not training_run_id:
        return

    try:
        training_run = AutoresearchTrainingRun.objects.select_related("pipeline__team").get(id=training_run_id)
    except AutoresearchTrainingRun.DoesNotExist:
        logger.warning(
            "autoresearch_training_run_not_found",
            task_run_id=str(task_run.id),
            training_run_id=training_run_id,
        )
        return

    # Idempotency guard: only process if still in RUNNING state.
    if training_run.status != AutoresearchTrainingRun.Status.RUNNING:
        logger.info(
            "autoresearch_training_run_already_processed",
            training_run_id=training_run_id,
            status=training_run.status,
        )
        return

    from products.tasks.backend.models import TaskRun

    if task_run.status in {TaskRun.Status.FAILED, TaskRun.Status.CANCELLED}:
        _mark_failed(training_run, error=task_run.error_message or "TaskRun did not complete successfully")
        return

    recipe_data = _extract_recipe(task_run)
    if recipe_data is None:
        _mark_failed(training_run, error="Agent did not produce a valid recipe")
        return

    try:
        _ingest_recipe(training_run, recipe_data, task_run)
    except Exception:
        logger.exception(
            "autoresearch_ingest_failed",
            training_run_id=training_run_id,
            task_run_id=str(task_run.id),
        )
        _mark_failed(training_run, error="Recipe ingestion failed — see server logs")


# ── Recipe extraction ──────────────────────────────────────────────────────────


def _extract_recipe(task_run: Any) -> dict | None:
    """
    Try to extract the recipe dict from the TaskRun.

    Priority:
    1. task_run.output — set by the agent calling set_output (validated JSON).
    2. S3 log fallback — parse the agent's last text message for JSON.
    """
    if task_run.output:
        try:
            _validate_recipe(task_run.output)
            return task_run.output
        except (ValidationError, Exception) as exc:
            logger.warning(
                "autoresearch_structured_output_invalid",
                task_run_id=str(task_run.id),
                error=str(exc),
            )
            # Fall through to log parsing

    return _extract_recipe_from_logs(task_run)


def _extract_recipe_from_logs(task_run: Any) -> dict | None:
    """Read S3 logs and extract the recipe JSON from the agent's last message."""
    from posthog.storage import object_storage

    try:
        log_content = object_storage.read(task_run.log_url, missing_ok=True) or ""
    except Exception:
        logger.exception("autoresearch_log_read_failed", task_run_id=str(task_run.id))
        return None

    if not log_content.strip():
        return None

    last_agent_text = _extract_last_agent_message(log_content)
    if not last_agent_text:
        return None

    raw = _extract_json_from_text(last_agent_text)
    if raw is None:
        return None

    try:
        _validate_recipe(raw)
        return raw
    except (ValidationError, Exception) as exc:
        logger.warning(
            "autoresearch_log_recipe_invalid",
            task_run_id=str(task_run.id),
            error=str(exc),
        )
        return None


def _validate_recipe(data: dict) -> None:
    """Validate recipe data against ModelRecipeOutput schema. Raises on invalid."""
    ModelRecipeOutput.model_validate(data)


def _extract_last_agent_message(log_content: str) -> str | None:
    """
    Walk JSONL log lines backwards to find the last agent text message.
    Mirrors the logic in custom_prompt_internals._check_logs.
    """
    lines = log_content.strip().split("\n")
    _AGENT_MSG_TYPES = {"agent_message", "agent_message_chunk"}
    trailing_parts: list[str] = []
    found_agent_msg = False

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        notification = entry.get("notification")
        if not isinstance(notification, dict):
            continue
        if notification.get("method") != "session/update":
            continue
        params = notification.get("params")
        update = params.get("update") if isinstance(params, dict) else None
        if not isinstance(update, dict):
            continue

        is_agent_msg = update.get("sessionUpdate") in _AGENT_MSG_TYPES
        if not found_agent_msg:
            if is_agent_msg:
                found_agent_msg = True
            else:
                continue
        if found_agent_msg and not is_agent_msg:
            break

        text = _extract_text_from_update(update)
        if text:
            trailing_parts.append(text)

    if not trailing_parts:
        return None
    trailing_parts.reverse()
    return "".join(trailing_parts)


def _extract_text_from_update(update: dict) -> str | None:
    content = update.get("content")
    if isinstance(content, dict) and content.get("type") == "text" and isinstance(content.get("text"), str):
        candidate = content["text"].strip()
        if candidate:
            return candidate
    message = update.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return None


def _extract_json_from_text(text: str) -> dict | None:
    """Extract a JSON object from text that may contain markdown or prose."""
    # 1. ```json ... ``` fenced code block
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1).strip())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # 2. ``` ... ``` generic code block
    match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1).strip())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # 3. Bare JSON object — try from each '{' to last '}'
    last_brace = text.rfind("}")
    if last_brace != -1:
        start = 0
        while True:
            brace_pos = text.find("{", start)
            if brace_pos == -1 or brace_pos >= last_brace:
                break
            try:
                result = json.loads(text[brace_pos : last_brace + 1])
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                start = brace_pos + 1

    # 4. Last resort — whole text
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    return None


# ── Recipe ingestion ───────────────────────────────────────────────────────────


def _recipe_hash(recipe_data: dict) -> str:
    canonical = {k: recipe_data.get(k) for k in ("feature_sql", "model_class", "model_params")}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


def _ingest_recipe(training_run: AutoresearchTrainingRun, recipe_data: dict, task_run: Any) -> None:
    """Materialise the recipe as AutoresearchModel + AutoresearchIteration records."""
    pipeline = training_run.pipeline
    now = django_timezone.now()
    recipe_hash = _recipe_hash(recipe_data)
    holdout_score = float(recipe_data.get("holdout_score", 0.0))

    # Archive any existing champion
    AutoresearchModel.objects.filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION).update(
        role=AutoresearchModel.Role.ARCHIVED, archived_at=now
    )

    # Persist the champion model
    explanation = recipe_data.get("model_explanation", {})
    champion = AutoresearchModel.objects.create(
        pipeline=pipeline,
        role=AutoresearchModel.Role.CHAMPION,
        recipe_hash=recipe_hash,
        model_recipe={
            "feature_sql": recipe_data.get("feature_sql", ""),
            "feature_transforms": recipe_data.get("feature_transforms", []),
            "model_class": recipe_data.get("model_class", "sklearn.linear_model.LogisticRegression"),
            "model_params": recipe_data.get("model_params", {}),
            "fit_signature": recipe_data.get("fit_signature", recipe_hash[:16]),
            "trained_on": recipe_data.get("trained_on", date.today().isoformat()),
            "holdout_score": holdout_score,
            "agent_description": recipe_data.get("agent_description", ""),
        },
        model_explanation=explanation,
        holdout_score=holdout_score,
        metrics={"holdout_auc": holdout_score, "sandbox": True},
        source_training_run=training_run,
        agent_description=recipe_data.get("agent_description", ""),
        trained_on_start=date.today(),
        trained_on_end=date.today(),
        is_preliminary=True,
        promoted_at=now,
    )

    # Persist iteration records
    iterations = recipe_data.get("iterations", [])
    best_score = holdout_score
    for record in iterations:
        iter_hash = record.get("recipe_hash") or _recipe_hash(
            {
                "feature_sql": "",
                "model_class": record.get("model_class", ""),
                "model_params": record.get("model_params", {}),
            }
        )
        iter_score = float(record.get("holdout_score", 0.0))
        AutoresearchIteration.objects.get_or_create(
            training_run=training_run,
            iteration_number=record.get("iteration_number", 0),
            defaults={
                "pipeline": pipeline,
                "recipe_hash": iter_hash,
                "recipe_snapshot": {
                    "model_class": record.get("model_class", ""),
                    "model_params": record.get("model_params", {}),
                    "holdout_score": iter_score,
                },
                "model_spec": {
                    "model_class": record.get("model_class", ""),
                    "model_params": record.get("model_params", {}),
                },
                "train_score": iter_score,
                "holdout_score": iter_score,
                "status": (
                    AutoresearchIteration.Status.KEPT
                    if record.get("status") == "kept"
                    else AutoresearchIteration.Status.DISCARDED
                ),
                "agent_description": record.get("agent_description", record.get("feature_summary", "")),
                "agent_confidence": None,
            },
        )
        best_score = max(best_score, iter_score)

    # Finish the training run
    training_run.iteration_count = max(len(iterations), 1)
    training_run.best_holdout_score = best_score
    training_run.status = AutoresearchTrainingRun.Status.COMPLETED
    training_run.completed_at = now
    training_run.save(update_fields=["iteration_count", "best_holdout_score", "status", "completed_at"])

    # Advance pipeline status
    pipeline.status = AutoresearchPipeline.Status.RUNNING
    pipeline.iteration_budget_remaining = max(0, pipeline.iteration_budget_remaining - training_run.iteration_budget)
    pipeline.save(update_fields=["status", "iteration_budget_remaining", "updated_at"])

    logger.info(
        "autoresearch_training_ingested",
        pipeline_id=str(pipeline.pk),
        training_run_id=str(training_run.pk),
        model_id=str(champion.pk),
        holdout_score=holdout_score,
        iteration_count=training_run.iteration_count,
    )


def _mark_failed(training_run: AutoresearchTrainingRun, error: str) -> None:
    training_run.status = AutoresearchTrainingRun.Status.FAILED
    training_run.completed_at = django_timezone.now()
    training_run.error = error[:2000]
    training_run.save(update_fields=["status", "completed_at", "error"])
    logger.warning(
        "autoresearch_training_failed",
        training_run_id=str(training_run.pk),
        pipeline_id=str(training_run.pipeline_id),
        error=error,
    )
