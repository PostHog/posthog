"""Enqueue retraining tasks for AutoML pipelines.

Retraining is the Karpathy-style iteration loop on top of bootstrap's first
model. Each invocation opens a fresh ``AutoMLPipelineRun(run_kind=RETRAIN)``
chained via ``parent_run_id`` to the previous winning run, and dispatches a
Task that runs the ``automl-retrain`` agent skill inside the same dedicated
AutoML sandbox image as bootstrap.

The agent's job:

1. Load the parent run via ``automl-get-run`` — what won last time?
2. Pick *one* knob to vary (preset / feature edits / sample size) based on
   the parent run's leaderboard + EDA.
3. Walk the CLI's skills/README.md decision tree, skipping steps that
   don't change.
4. Record the result + evaluate the three displacement gates
   (offline + realized + autonomy).
5. Conditionally displace the existing champion.

Design rationale + search-space bounds live in the durable ``/phs automl``
skill (``design.md`` § "Retraining iteration loop" and
``references/retraining-skill-outline.md``). Keep this module to brief
construction + Task enqueue — the skill is the workflow.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from posthog.models import Team

from products.tasks.backend.models import Task
from products.tasks.backend.services.sandbox import SandboxTemplate

from ..models import AutoMLPipeline, AutoMLPipelineRun
from .bootstrap import (
    _LOCAL_S3_AWS_ACCESS_KEY_ID,
    _LOCAL_S3_AWS_REGION,
    _LOCAL_S3_AWS_SECRET_ACCESS_KEY,
    _LOCAL_S3_ENDPOINT,
    _build_gate_config,
    _build_pipeline_spec,
    _extract_training_query,
)


def enqueue_retraining(
    *,
    pipeline: AutoMLPipeline,
    user_id: int,
    run_id: UUID,
    task_slug: str,
    task_workspace_root: str,
    parent_run: AutoMLPipelineRun,
) -> Task:
    """Create a Task that will run a retraining iteration on the pipeline.

    Pure brief-builder + Task-creator, same shape as
    ``bootstrap.enqueue_bootstrap_training``. The surrounding facade owns the
    ``AutoMLPipelineRun`` row's lifecycle — creates it with
    ``run_kind=RETRAIN`` + ``parent_run_id`` before this call, marks it
    failed on this raising.

    Returns the created ``Task`` so the caller can stash its id on the run row.
    """
    team = Team.objects.get(id=pipeline.team_id)
    return Task.create_and_run(
        team=team,
        title=f"AutoML retrain: {pipeline.name}",
        description=_build_retraining_brief(
            pipeline,
            run_id=run_id,
            task_slug=task_slug,
            task_workspace_root=task_workspace_root,
            parent_run=parent_run,
        ),
        origin_product=Task.OriginProduct.AUTOML,
        user_id=user_id,
        mode="background",
        # Same scope set as bootstrap — the retrain agent needs to read taxonomy
        # and write predictions / model versions.
        posthog_mcp_scopes="full",
        create_pr=False,
        # Same dedicated AutoML sandbox image as bootstrap.
        sandbox_template=SandboxTemplate.AUTOML,
    )


def _build_retraining_brief(
    pipeline: AutoMLPipeline,
    *,
    run_id: UUID,
    task_slug: str,
    task_workspace_root: str,
    parent_run: AutoMLPipelineRun,
) -> str:
    """Build the task description handed to the retraining agent.

    Same thin-pointer shape as the bootstrap brief — points at the
    ``automl-retrain`` skill plus the per-pipeline payload. The retraining
    skill carries the parent-run reasoning, one-knob-per-iteration decision
    tree, and three-gate evaluation logic.

    Adds a `## Parent run` section that summarizes the previous winning run
    (metrics, leaderboard top-5, EDA flags) so the agent can pick a knob
    without an extra MCP round-trip just to read its parent.
    """
    spec_json = json.dumps(_build_pipeline_spec(pipeline), indent=2, default=str)
    gates_json = json.dumps(_build_gate_config(pipeline), indent=2, default=str)
    training_query = _extract_training_query(pipeline)
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
        },
        indent=2,
    )
    parent_summary_json = json.dumps(_summarize_parent_run(parent_run), indent=2, default=str)

    return (
        f"# AutoML retrain: {pipeline.name}\n"
        "\n"
        "Run the `automl-retrain` skill. The skill carries the PostHog-side\n"
        "retraining contract (parent-run reasoning, one-knob-per-iteration\n"
        "decision tree, three-gate evaluation, conditional displacement); the\n"
        "ML/EDA/training flow itself lives on the CLI side in\n"
        "`automl-cli/skills/README.md` (decision tree) and the four CLI skills\n"
        "it links to (`scope-modeling-task`, `tune-hogql-query`,\n"
        "`eda-on-features`, `run-train-predict`). Iterate on recoverable errors;\n"
        "don't bail at the first non-zero exit.\n"
        "\n"
        "## Run context\n"
        "\n"
        "Pass `--task $task_slug --s3-endpoint $s3_endpoint` on every CLI\n"
        "invocation. Surface `run_id` on every `automl-record-*` MCP call so\n"
        "the same `AutoMLPipelineRun` row accumulates EDA / training / outcome\n"
        "updates. Export the AWS keys before any S3-touching command so\n"
        "pyarrow / boto3 inside the CLI can authenticate to local MinIO:\n"
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
        "## Parent run\n"
        "\n"
        "This retraining iteration is anchored on the parent run below — the\n"
        "previous winning recipe. Use its metrics + leaderboard + EDA flags to\n"
        "decide which single knob to vary. Don't change multiple knobs at\n"
        "once; the iteration log loses meaning if every variable shifts. See\n"
        "the skill's decision tree for picking the knob.\n"
        "\n"
        "```json\n"
        f"{parent_summary_json}\n"
        "```\n"
        "\n"
        "## Pipeline spec\n"
        "\n"
        "Treat every field as authoritative; do not edit the config. Convert\n"
        "this to the CLI's `spec.yaml` via `Workspace.write_spec(...)` after\n"
        "`scope-modeling-task` confirms the task is still well-scoped (it\n"
        "should be — retraining doesn't rescope).\n"
        "\n"
        "```json\n"
        f"{spec_json}\n"
        "```\n"
        "\n"
        "## Promotion gates\n"
        "\n"
        "Apply per the skill's three-gate logic (offline + realized + autonomy).\n"
        "Unlike bootstrap, retraining *can* displace an existing champion — see\n"
        "the skill for the precise displacement rules.\n"
        "\n"
        "```json\n"
        f"{gates_json}\n"
        "```\n"
        "\n"
        "## Training-population HogQL\n"
        "\n"
        "Same training population as the parent run. If the parent's EDA\n"
        "flagged leakage or low-signal features and you're varying the feature\n"
        "set, edit this query — pass via `prepare-from-hogql --task` so the\n"
        "edited query lands versioned in the workspace at `queries/v{N}.sql`.\n"
        "\n"
        "```hogql\n"
        f"{training_query}\n"
        "```\n"
    )


def _summarize_parent_run(parent_run: AutoMLPipelineRun) -> dict[str, Any]:
    """Compact summary of the parent run for the retraining brief.

    Pulls the fields the agent needs to reason about the next knob without
    making an MCP round-trip. Excludes the full outcome report (the agent
    can pull that via `automl-get-run` if needed); excludes raw EDA blobs
    larger than ~5 KB by truncating list fields.
    """
    eda = parent_run.eda_result or {}
    training = parent_run.training_result or {}
    return {
        "run_id": str(parent_run.id),
        "run_kind": parent_run.run_kind,
        "task_slug": parent_run.task_slug,
        "cli_run_id": parent_run.cli_run_id,
        "completed_at": parent_run.completed_at.isoformat() if parent_run.completed_at else None,
        "created_model_version_id": (
            str(parent_run.created_model_version_id) if parent_run.created_model_version_id else None
        ),
        "training_summary": {
            "metrics": training.get("metrics", {}),
            "leaderboard_top5": training.get("leaderboard_top5", []),
            "eval_metric": training.get("eval_metric", ""),
            "problem_type": training.get("problem_type", ""),
        },
        "eda_summary": {
            "n_rows": eda.get("n_rows"),
            "n_cols": eda.get("n_cols"),
            "target_type": eda.get("target_type"),
            "class_balance": eda.get("class_balance"),
            # Top 10 of each — full lists may be much longer.
            "top_signal_features": (eda.get("top_signal_features") or [])[:10],
            "suspect_target_leakage": (eda.get("suspect_target_leakage") or [])[:10],
            "low_signal_features": (eda.get("low_signal_features") or [])[:10],
            "drop_constant_or_near_constant": (eda.get("drop_constant_or_near_constant") or [])[:10],
            "drop_redundant_keep_first": (eda.get("drop_redundant_keep_first") or [])[:10],
        },
    }
