"""
Temporal workflow scaffold for autoresearch inference.

The inference workflow is a regular Temporal workflow (not a TaskRun/agent sandbox)
because scoring doesn't need an agent loop — it's a deterministic pipeline:
  load recipe → build feature matrix → score users → emit prediction events.

Training runs through Task/TaskRun (see stub_training.py for the current stub).

This file contains the scaffolded workflow and activity signatures. The activity
implementations delegate to products.autoresearch.backend.inference so the same
code path is exercised by both:
  - management command: autoresearch_score (direct call, local dev)
  - Temporal workflow: AutoresearchInferenceWorkflow (production)
"""

from dataclasses import dataclass
from typing import Optional

import structlog

from products.autoresearch.backend.inference import run_inference_for_pipeline
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline

logger = structlog.get_logger(__name__)


@dataclass
class InferenceWorkflowInput:
    pipeline_id: str
    model_id: str
    prediction_date: str  # ISO date string, e.g. "2026-05-26"


@dataclass
class InferenceWorkflowResult:
    run_id: str
    rows_scored: int
    status: str
    error: Optional[str] = None


# ── Temporal activities (to be decorated with @activity.defn once wired) ──


def activity_load_champion(pipeline_id: str) -> dict:
    """
    Load the champion model recipe for a pipeline.
    Returns model_id and recipe dict.
    """
    pipeline = AutoresearchPipeline.objects.select_related("team").get(pk=pipeline_id)
    champion = (
        AutoresearchModel.objects.filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
        .order_by("-created_at")
        .first()
    )
    if not champion:
        raise ValueError(f"No champion model for pipeline {pipeline_id}")
    return {"model_id": str(champion.pk), "recipe": champion.model_recipe}


def activity_run_inference(pipeline_id: str, model_id: str) -> dict:
    """
    Score the inference population and emit autoresearch_prediction events.
    Delegates to the shared inference module.
    """
    pipeline = AutoresearchPipeline.objects.select_related("team").get(pk=pipeline_id)
    model = AutoresearchModel.objects.get(pk=model_id)
    run = run_inference_for_pipeline(pipeline=pipeline, model=model)
    return {
        "run_id": str(run.pk),
        "rows_scored": run.rows_scored or 0,
        "status": run.status,
        "error": run.error or None,
    }


# ── Workflow stub (to be decorated with @workflow.defn once wired) ─────────


def run_inference_workflow(inp: InferenceWorkflowInput) -> InferenceWorkflowResult:
    """
    Stub workflow logic — runs activities sequentially.
    Replace with real Temporal @workflow.defn + activity.execute_activity calls
    when wiring into the Temporal worker.
    """
    logger.info(
        "autoresearch_inference_workflow_start",
        pipeline_id=inp.pipeline_id,
        prediction_date=inp.prediction_date,
    )

    champion_info = activity_load_champion(inp.pipeline_id)
    result = activity_run_inference(
        pipeline_id=inp.pipeline_id,
        model_id=champion_info["model_id"],
    )

    return InferenceWorkflowResult(
        run_id=result["run_id"],
        rows_scored=result["rows_scored"],
        status=result["status"],
        error=result.get("error"),
    )
