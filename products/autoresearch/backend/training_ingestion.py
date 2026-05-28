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

from posthog.api.capture import capture_internal

from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.promotion import complete_training_run
from products.autoresearch.backend.training import ModelRecipeOutput

logger = structlog.get_logger(__name__)

ITERATION_EVENT_NAME = "autoresearch_iteration"
ITERATION_EVENT_SOURCE = "autoresearch_training"


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

    # Agent-recorded path: if the agent persisted iterations directly via the new MCP write tools
    # (autoresearch-training-runs-iterations-create), there is no set_output blob to parse.
    # Finalize through the server-side promotion flow instead. Falls through to the legacy
    # set_output parser when no iterations exist.
    if AutoresearchIteration.objects.filter(training_run=training_run).exists():
        try:
            complete_training_run(training_run)
        except Exception:
            logger.exception(
                "autoresearch_agent_recorded_complete_failed",
                training_run_id=training_run_id,
                task_run_id=str(task_run.id),
            )
            _mark_failed(training_run, error="Agent-recorded run completion failed — see server logs")
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

    _emit_iteration_events(training_run=training_run, iterations=iterations, pipeline=pipeline)

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


def _emit_iteration_events(
    training_run: AutoresearchTrainingRun,
    iterations: list[dict[str, Any]],
    pipeline: AutoresearchPipeline,
) -> None:
    """
    Emit one autoresearch_iteration event per iteration to PostHog.

    Events are pipeline-scoped (synthetic distinct_id) so they don't create
    spurious person profiles and can be queried by pipeline in PostHog.
    Emission failures are logged and swallowed — they must not fail ingestion.
    """
    if not iterations:
        return

    token = pipeline.team.api_token
    # Synthetic distinct_id groups all pipeline events without creating real persons.
    distinct_id = f"$autoresearch:pipeline:{pipeline.pk}"
    now = django_timezone.now()

    emitted = 0
    errors = 0
    for record in iterations:
        iter_score = record.get("holdout_score")
        train_score = record.get("train_score") or iter_score
        status_raw = record.get("status", "discarded")
        model_class = record.get("model_class", "")
        description = (record.get("agent_description") or record.get("feature_summary") or "")[:500]

        iter_hash = record.get("recipe_hash") or _recipe_hash(
            {
                "feature_sql": "",
                "model_class": model_class,
                "model_params": record.get("model_params", {}),
            }
        )

        props: dict[str, Any] = {
            "$autoresearch_pipeline_id": str(pipeline.pk),
            "$autoresearch_training_run_id": str(training_run.pk),
            "$autoresearch_iteration_number": record.get("iteration_number", 0),
            "$autoresearch_iteration_status": status_raw,
            "$autoresearch_holdout_score": float(iter_score) if iter_score is not None else None,
            "$autoresearch_train_score": float(train_score) if train_score is not None else None,
            "$autoresearch_model_class": model_class,
            "$autoresearch_agent_description": description,
            "$autoresearch_recipe_hash": iter_hash[:16],
            "$autoresearch_target_event": pipeline.target_event,
            "$autoresearch_horizon_days": pipeline.horizon_days,
        }

        try:
            response = capture_internal(
                token=token,
                event_name=ITERATION_EVENT_NAME,
                event_source=ITERATION_EVENT_SOURCE,
                distinct_id=distinct_id,
                timestamp=now,
                properties=props,
                process_person_profile=False,
            )
            response.raise_for_status()
            emitted += 1
        except Exception:
            errors += 1
            logger.exception(
                "autoresearch_iteration_event_emit_failed",
                pipeline_id=str(pipeline.pk),
                training_run_id=str(training_run.pk),
                iteration_number=record.get("iteration_number"),
            )

    logger.info(
        "autoresearch_iteration_events_emitted",
        pipeline_id=str(pipeline.pk),
        training_run_id=str(training_run.pk),
        emitted=emitted,
        errors=errors,
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
