"""
Temporal workflow for autoresearch inference.

The inference workflow is a regular Temporal workflow (not a TaskRun/agent sandbox)
because scoring is a deterministic pipeline:
  load champion recipe → build feature matrix → score users → emit prediction events.

Training still runs through Task/TaskRun sandboxes (see training.py).

Activities are synchronous — Temporal runs them in a thread pool, which is correct
for Django ORM + HogQL queries. Workflows are async and only orchestrate activities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from products.autoresearch.backend.inference import run_inference_for_pipeline
    from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline

from posthog.temporal.common.base import PostHogWorkflow

logger = structlog.get_logger(__name__)


# ── I/O dataclasses ──────────────────────────────────────────────────────────


@dataclass
class InferenceWorkflowInput:
    pipeline_id: str
    prediction_date: str  # ISO date string, e.g. "2026-05-26"


@dataclass
class InferenceWorkflowResult:
    run_id: str
    rows_scored: int
    status: str
    error: Optional[str] = None


@dataclass
class LoadChampionInput:
    pipeline_id: str


@dataclass
class LoadChampionResult:
    model_id: str


@dataclass
class RunInferenceInput:
    pipeline_id: str
    model_id: str


@dataclass
class RunInferenceResult:
    run_id: str
    rows_scored: int
    status: str
    error: Optional[str] = None


# ── Activities ───────────────────────────────────────────────────────────────


@activity.defn(name="autoresearch-inference.load_champion")
def activity_load_champion(inp: LoadChampionInput) -> LoadChampionResult:
    """Load the champion model for a pipeline. Raises if none exists."""
    pipeline = AutoresearchPipeline.objects.get(pk=inp.pipeline_id)
    champion = (
        AutoresearchModel.objects.filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
        .order_by("-created_at")
        .first()
    )
    if not champion:
        raise ValueError(f"No champion model for pipeline {inp.pipeline_id}")
    return LoadChampionResult(model_id=str(champion.pk))


@activity.defn(name="autoresearch-inference.run_inference")
def activity_run_inference(inp: RunInferenceInput) -> RunInferenceResult:
    """Score the inference population and emit autoresearch_prediction events."""
    pipeline = AutoresearchPipeline.objects.select_related("team").get(pk=inp.pipeline_id)
    model = AutoresearchModel.objects.get(pk=inp.model_id)
    run = run_inference_for_pipeline(pipeline=pipeline, model=model)
    return RunInferenceResult(
        run_id=str(run.pk),
        rows_scored=run.rows_scored or 0,
        status=run.status,
        error=run.error or None,
    )


# ── Workflow ─────────────────────────────────────────────────────────────────

# Load champion is a cheap DB read; score can take minutes for large populations.
_LOAD_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5))
_SCORE_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=30))


@workflow.defn(name="autoresearch-inference")
class AutoresearchInferenceWorkflow(PostHogWorkflow):
    """
    Temporal workflow that runs daily inference for one autoresearch pipeline.

    Steps:
    1. Load the champion model for the pipeline.
    2. Score the inference population and emit autoresearch_prediction events.

    Both steps delegate to products.autoresearch.backend.inference so the same
    code is exercised by both the Temporal workflow and the local management
    command (autoresearch_score).
    """

    inputs_cls = InferenceWorkflowInput

    @workflow.run
    async def run(self, inp: InferenceWorkflowInput) -> InferenceWorkflowResult:
        workflow.logger.info(
            "autoresearch_inference_workflow_start",
            pipeline_id=inp.pipeline_id,
            prediction_date=inp.prediction_date,
        )

        champion = await workflow.execute_activity(
            activity_load_champion,
            LoadChampionInput(pipeline_id=inp.pipeline_id),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=_LOAD_RETRY,
        )

        result = await workflow.execute_activity(
            activity_run_inference,
            RunInferenceInput(pipeline_id=inp.pipeline_id, model_id=champion.model_id),
            start_to_close_timeout=timedelta(hours=2),
            retry_policy=_SCORE_RETRY,
        )

        workflow.logger.info(
            "autoresearch_inference_workflow_complete",
            pipeline_id=inp.pipeline_id,
            run_id=result.run_id,
            rows_scored=result.rows_scored,
            status=result.status,
        )

        return InferenceWorkflowResult(
            run_id=result.run_id,
            rows_scored=result.rows_scored,
            status=result.status,
            error=result.error,
        )
