"""Enqueue inference (scoring) tasks for AutoML pipelines.

Inference is the recurring scoring step on top of an active pipeline's
champion model. Each invocation opens a fresh ``AutoMLPipelineRun(run_kind=
INFERENCE)`` chained via ``parent_run_id`` to the champion's training run,
and dispatches a Task that runs the ``automl-inference`` agent skill inside
the same dedicated AutoML sandbox image as bootstrap and retrain.

The agent's job is intentionally narrow:

1. Run ``automl refresh-task --task <slug> --project-id <pid>`` — fetches a
   fresh inference snapshot, loads the champion model, scores it, writes
   ``predictions.parquet`` into the workspace.
2. Parse the CLI's stdout JSON manifest.
3. Call ``automl-record-inference-outcome`` with the manifest. The
   PostHog-side event-emission step (Phase 2) will read ``predictions_uri``
   out of that record and emit one ``$automl_prediction`` event per row.

Hackathon scope: dispatch is manual — call ``api.infer(...)`` directly or
hit the ``infer/`` DRF action / ``automl-infer`` MCP tool. A per-pipeline
Temporal schedule driven by ``pipeline.inference_cadence`` is the natural
follow-up (see ``automl-cli/skills/schedule-refresh.md`` for the
recommended integration shape) — this module stays scheduler-agnostic.
"""

from __future__ import annotations

import json
from uuid import UUID

from posthog.models import Team

from products.tasks.backend.models import Task
from products.tasks.backend.services.sandbox import SandboxTemplate

from ..models import AutoMLPipeline, AutoMLPipelineRun
from ..training.bootstrap import (
    _LOCAL_S3_AWS_ACCESS_KEY_ID,
    _LOCAL_S3_AWS_REGION,
    _LOCAL_S3_AWS_SECRET_ACCESS_KEY,
    _LOCAL_S3_ENDPOINT,
    _build_pipeline_spec,
)


def enqueue_inference(
    *,
    pipeline: AutoMLPipeline,
    user_id: int,
    run_id: UUID,
    task_slug: str,
    task_workspace_root: str,
    parent_run: AutoMLPipelineRun,
) -> Task:
    """Create a Task that will run a single scoring iteration.

    Pure brief-builder + Task-creator, same shape as
    ``bootstrap.enqueue_bootstrap_training`` and
    ``retrain.enqueue_retraining``. The surrounding facade owns the
    ``AutoMLPipelineRun`` row's lifecycle — creates it with
    ``run_kind=INFERENCE`` + ``parent_run_id`` before this call, marks it
    failed on this raising.

    Returns the created ``Task`` so the caller can stash its id on the run row.
    """
    team = Team.objects.get(id=pipeline.team_id)
    return Task.create_and_run(
        team=team,
        title=f"AutoML inference: {pipeline.name}",
        description=_build_inference_brief(
            pipeline,
            run_id=run_id,
            task_slug=task_slug,
            task_workspace_root=task_workspace_root,
            parent_run=parent_run,
        ),
        origin_product=Task.OriginProduct.AUTOML,
        user_id=user_id,
        mode="background",
        # Same scope set as bootstrap/retrain — the inference agent calls
        # `automl-record-inference-outcome` to checkpoint.
        posthog_mcp_scopes="full",
        create_pr=False,
        sandbox_template=SandboxTemplate.AUTOML,
    )


def _build_inference_brief(
    pipeline: AutoMLPipeline,
    *,
    run_id: UUID,
    task_slug: str,
    task_workspace_root: str,
    parent_run: AutoMLPipelineRun,
) -> str:
    """Build the task description handed to the inference agent.

    Same thin-pointer shape as the bootstrap and retrain briefs — points at
    the ``automl-inference`` skill plus the per-pipeline payload. The skill
    carries the workflow; this brief carries only data the agent can't
    discover for itself (run_id, parent run id, task slug, S3 creds).
    """
    spec_json = json.dumps(_build_pipeline_spec(pipeline), indent=2, default=str)
    inference_query = _extract_inference_query(pipeline)
    run_ctx_json = json.dumps(
        {
            "run_id": str(run_id),
            "pipeline_id": str(pipeline.id),
            "task_slug": task_slug,
            "task_workspace_root": task_workspace_root,
            "s3_endpoint": _LOCAL_S3_ENDPOINT,
            "aws_access_key_id": _LOCAL_S3_AWS_ACCESS_KEY_ID,
            "aws_secret_access_key": _LOCAL_S3_AWS_SECRET_ACCESS_KEY,
            "aws_default_region": _LOCAL_S3_AWS_REGION,
            "parent_run_id": str(parent_run.id),
            "champion_model_run_id": parent_run.cli_run_id or None,
            "champion_model_version_id": (
                str(parent_run.created_model_version_id) if parent_run.created_model_version_id else None
            ),
        },
        indent=2,
    )

    return (
        f"# AutoML inference: {pipeline.name}\n"
        "\n"
        "Run the `automl-inference` skill. The skill carries the PostHog-side\n"
        "inference contract (single CLI invocation, single MCP checkpoint).\n"
        "The ML/data-fetch flow itself lives on the CLI side in\n"
        "`automl-cli/skills/schedule-refresh.md` (the integration contract for\n"
        "`automl refresh-task`).\n"
        "\n"
        "Unlike bootstrap and retrain, this run does NOT train a model — the\n"
        "champion at MODEL_HEAD is what scores the population. Iteration\n"
        "happens via retraining, not via inference. If the CLI invocation\n"
        "fails, surface the failure verbatim via\n"
        "`automl-record-inference-outcome` with `status=failed` and a\n"
        "compact `failure_reason` tag — don't try to repair the model from\n"
        "this run.\n"
        "\n"
        "## Run context\n"
        "\n"
        "Pass `--task $task_slug --s3-endpoint $s3_endpoint` on the\n"
        "`refresh-task` invocation. Surface `run_id` on the\n"
        "`automl-record-inference-outcome` call so the same\n"
        "`AutoMLPipelineRun` row gets the manifest stamped onto it. Export the\n"
        "AWS keys before any S3-touching command so pyarrow / boto3 inside\n"
        "the CLI can authenticate to local MinIO:\n"
        "\n"
        "```bash\n"
        "export AWS_ACCESS_KEY_ID=$aws_access_key_id\n"
        "export AWS_SECRET_ACCESS_KEY=$aws_secret_access_key\n"
        "export AWS_DEFAULT_REGION=$aws_default_region\n"
        "```\n"
        "\n"
        "```json\n"
        f"{run_ctx_json}\n"
        "```\n"
        "\n"
        "## Pipeline spec\n"
        "\n"
        "Read-only context for the agent — no edits required for inference.\n"
        "The CLI reads the workspace's spec.yaml directly.\n"
        "\n"
        "```json\n"
        f"{spec_json}\n"
        "```\n"
        "\n"
        "## Inference-population HogQL\n"
        "\n"
        "This is the inference query (no target column, no horizon truncation).\n"
        "`refresh-task` reads the workspace's HEAD query by default, which is\n"
        "the *training* query. Pass `--query` (or `--query-file`) to override\n"
        "with the inference query below for this run.\n"
        "\n"
        "```hogql\n"
        f"{inference_query}\n"
        "```\n"
    )


def _extract_inference_query(pipeline: AutoMLPipeline) -> str:
    """Extract the inference HogQL string from the pipeline's inference_population.

    Mirrors ``bootstrap._extract_training_query`` shape. Returns a placeholder
    if the inference_population isn't a HogQL spec — the agent surfaces a
    clean failure rather than silently scoring the wrong population.
    """
    pop = pipeline.inference_population or {}
    if pop.get("kind") == "hogql":
        return pop.get("query", "").strip()
    return "-- inference_population is not a HogQL query; agent should fail with `inference_query_unavailable`."
