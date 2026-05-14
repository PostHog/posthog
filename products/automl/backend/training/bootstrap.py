"""Enqueue bootstrap training tasks for AutoML pipelines.

Builds the task description handed to the `tasks` product via
``Task.create_and_run``. The real ML runs inside ``ProcessTaskWorkflow``'s
sandbox; this module is just the bridge that constructs the per-pipeline
payload the agent operates on.

The workflow content lives in the ``automl-bootstrap`` agent skill
(``products/automl/skills/automl-bootstrap/SKILL.md``) which gets baked into
the sandbox image. We only stamp the per-pipeline data here: the pipeline
spec, the promotion gates, and the training-population HogQL — everything
else (workflow steps, CLI surface, pitfalls, failure-recovery framework)
lives in the skill so the agent can iterate on errors using its own loop
instead of following a frozen contract.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from django.utils.text import slugify

from posthog.models import Team

from products.tasks.backend.models import Task
from products.tasks.backend.services.sandbox import SandboxTemplate

from ..facade.enums import TaskType
from ..models import AutoMLPipeline

# Local-dev MinIO endpoint. Production runs without an endpoint override
# (real AWS S3 via instance role). For now this is hardcoded — once the
# scheduled inference workflow lands we'll wire it off a setting per env.
_LOCAL_S3_ENDPOINT = "http://localhost:19000"


def derive_task_slug(pipeline: AutoMLPipeline) -> str:
    """Derive the ``--task <slug>`` name passed to `automl-cli`.

    Uses Django's `slugify` (kebab-case) then converts to snake_case since
    the CLI's `scope-modeling-task.md` examples use snake (`weekly_churn`,
    `user_activity_tier`). Stable across runs of the same pipeline so the
    workspace path is predictable.

    Falls back to a deterministic id-based slug if the pipeline name is all
    non-slug characters — the CLI rejects an empty `--task`.
    """
    slug = slugify(pipeline.name).replace("-", "_")
    return slug or f"pipeline_{pipeline.id.hex[:8]}"


def derive_task_workspace_root(task_slug: str) -> str:
    """The ``s3://automl/tasks/<task_slug>/`` prefix the CLI writes to."""
    return f"s3://automl/tasks/{task_slug}"


# Per-task-type fallback gates used when the pipeline's config doesn't carry
# its own ``success_criteria``. These are deliberately permissive — the goal
# is "don't promote an obviously broken model", not "match the user's bar".
# Users tighten via ``config.success_criteria``.
_DEFAULT_GATES: dict[TaskType, dict[str, Any]] = {
    TaskType.CLASSIFICATION: {
        "primary_metric": "accuracy",
        "direction": "higher_is_better",
        "floor": 0.6,
    },
    TaskType.REGRESSION: {
        "primary_metric": "r2",
        "direction": "higher_is_better",
        "floor": 0.3,
    },
    TaskType.CLUSTERING: {
        "primary_metric": "silhouette",
        "direction": "higher_is_better",
        "floor": 0.2,
    },
    TaskType.FORECASTING: {
        "primary_metric": "smape",
        "direction": "lower_is_better",
        "ceiling": 0.3,
    },
}


def enqueue_bootstrap_training(
    *,
    pipeline: AutoMLPipeline,
    user_id: int,
    run_id: UUID,
    task_slug: str,
    task_workspace_root: str,
) -> Task:
    """Create a `Task` that will train the pipeline's first model in a sandbox.

    Pure brief-builder + Task-creator. The surrounding facade owns the
    ``AutoMLPipelineRun`` row's lifecycle — it creates the row before this
    call (so ``run_id`` exists) and marks it failed on the way out if this
    call raises. Returns the created `Task` so the caller can stash its id.

    Raises whatever `Task.create_and_run` raises (missing User, GitHub integration
    issues, etc.) — the caller is responsible for marking the pipeline FAILED
    and the run failed on bubble-up.
    """
    team = Team.objects.get(id=pipeline.team_id)
    return Task.create_and_run(
        team=team,
        title=f"AutoML bootstrap: {pipeline.name}",
        description=_build_orchestration_brief(
            pipeline,
            run_id=run_id,
            task_slug=task_slug,
            task_workspace_root=task_workspace_root,
        ),
        origin_product=Task.OriginProduct.AUTOML,
        user_id=user_id,
        # Batch training, no live user interaction — matches the Signals research pattern.
        mode="background",
        # Training agent needs full read access to the team's data taxonomy + write
        # access to emit prediction events. Narrow scopes once the training contract
        # stabilizes — tracked in the security-audit follow-ups.
        posthog_mcp_scopes="full",
        # AutoML produces model artifacts in object storage, not git commits.
        create_pr=False,
        # Route onto the dedicated AutoML sandbox image — extends the base
        # with autogluon + torch + polars preinstalled so the `posthog-automl-cli`
        # editable install is near-instant instead of ~5 min.
        sandbox_template=SandboxTemplate.AUTOML,
    )


def _build_orchestration_brief(
    pipeline: AutoMLPipeline,
    *,
    run_id: UUID,
    task_slug: str,
    task_workspace_root: str,
) -> str:
    """Build the task description handed to the bootstrap agent.

    The description is intentionally thin: a pointer to the
    ``automl-bootstrap`` skill (which itself points to `automl-cli`'s own
    `skills/README.md` decision tree for the ML/EDA/training flow), plus
    the per-pipeline payload the agent consumes (spec, gates, training
    query, task slug, workspace root, run id, S3 endpoint).

    The skill loads via the agent's normal skill-discovery mechanism inside
    the sandbox — keeping the dynamic content small keeps the prompt cheap
    and lets the skill evolve without rebuilding image artifacts.
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
        },
        indent=2,
    )

    return (
        f"# AutoML bootstrap: {pipeline.name}\n"
        "\n"
        "Run the `automl-bootstrap` skill. The skill carries the PostHog-side\n"
        "workflow contract (CLI install, MCP checkpoints, promotion gates, run\n"
        "lifecycle); the ML/EDA/training flow itself lives on the CLI side in\n"
        "`automl-cli/skills/README.md` (decision tree) and the four CLI skills it\n"
        "links to (`scope-modeling-task`, `tune-hogql-query`, `eda-on-features`,\n"
        "`run-train-predict`). Iterate on recoverable errors; don't bail at the\n"
        "first non-zero exit.\n"
        "\n"
        "## Run context\n"
        "\n"
        "Pass `--task` and `--s3-endpoint` on every CLI invocation. Surface\n"
        "`run_id` on every `automl-record-*` MCP call so the same\n"
        "`AutoMLPipelineRun` row gets EDA / training / outcome updates.\n"
        "\n"
        "```json\n"
        f"{run_ctx_json}\n"
        "```\n"
        "\n"
        "## Pipeline spec\n"
        "\n"
        "Treat every field as authoritative; do not edit the config. Convert this\n"
        "to the CLI's `spec.yaml` via `Workspace.write_spec(...)` after\n"
        "`scope-modeling-task` confirms the task is well-scoped (see CLI skill).\n"
        "\n"
        "```json\n"
        f"{spec_json}\n"
        "```\n"
        "\n"
        "## Promotion gates\n"
        "\n"
        "Apply after training reports back. Bootstrap never auto-displaces an\n"
        "existing champion — see the bootstrap skill's promotion section for the\n"
        "precondition check.\n"
        "\n"
        "```json\n"
        f"{gates_json}\n"
        "```\n"
        "\n"
        "## Training-population HogQL\n"
        "\n"
        "Write this to a file and pass via `prepare-from-hogql --task` so it lands\n"
        "versioned in the workspace at `queries/v{N}.sql`. If the CLI rejects it\n"
        "with a parse / type error, iterate using the CLI's `tune-hogql-query`\n"
        "skill — do not look at `dev_queries/`, that directory is poison per the\n"
        "CLI's own hard rules.\n"
        "\n"
        "```hogql\n"
        f"{training_query}\n"
        "```\n"
    )


def _extract_training_query(pipeline: AutoMLPipeline) -> str:
    """Pull the HogQL string off the pipeline's training_population.

    Only ``kind: hogql`` populations carry an inline query string; other kinds
    (saved cohort, recipe-derived, etc.) emit an empty string here. The brief's
    step 2 will fail on an empty heredoc, surfacing as ``snapshot_fetch_failed``
    — exactly the failure mode we want when the population shape isn't
    HogQL-shaped.
    """
    pop = pipeline.training_population if isinstance(pipeline.training_population, dict) else {}
    if pop.get("kind") == "hogql":
        return str(pop.get("query") or "")
    return ""


def _build_pipeline_spec(pipeline: AutoMLPipeline) -> dict[str, Any]:
    """JSON-serializable summary of the pipeline for the orchestration brief.

    Mirrors the shape we'll persist as the durable `pipeline_spec.json` once the
    real training contract lands. Excludes server-only fields (created_by_id,
    timestamps) — those aren't useful inside the sandbox.
    """
    return {
        "pipeline_id": str(pipeline.id),
        "team_id": pipeline.team_id,
        "task_type": pipeline.task_type,
        "autonomy": pipeline.autonomy,
        "config": pipeline.config,
        "training_population": pipeline.training_population,
        "inference_population": pipeline.inference_population,
        "inference_cadence": pipeline.inference_cadence,
        "retraining_cadence": pipeline.retraining_cadence,
        "output_property_name": pipeline.output_property_name,
    }


def _build_gate_config(pipeline: AutoMLPipeline) -> dict[str, Any]:
    """Derive the promotion-gate config the agent evaluates after training.

    Precedence:
      1. ``pipeline.config["success_criteria"]`` if it's a non-empty dict —
         this is the user's explicit override authored at pipeline setup time.
      2. Task-type defaults in ``_DEFAULT_GATES`` — permissive floors meant to
         catch obviously broken models without second-guessing the user's bar.

    Returns the dict embedded into the brief verbatim. Shape: a mapping with
    ``primary_metric``, ``direction``, and either ``floor`` (higher_is_better)
    or ``ceiling`` (lower_is_better). Source provenance is included in
    ``source`` so the agent can mention it in the outcome report.
    """
    user_criteria = pipeline.config.get("success_criteria") if isinstance(pipeline.config, dict) else None
    if isinstance(user_criteria, dict) and user_criteria:
        return {**user_criteria, "source": "pipeline_config"}

    try:
        defaults = _DEFAULT_GATES[TaskType(pipeline.task_type)]
    except (KeyError, ValueError):
        # Unknown task type slipped past validation — fall back to a no-op gate
        # that records but never auto-promotes. The agent will leave the model
        # as a challenger and surface the unknown task type in the report.
        return {"primary_metric": None, "direction": None, "source": "fallback_no_auto_promote"}
    return {**defaults, "source": "task_type_default"}
