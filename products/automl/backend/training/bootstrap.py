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

from posthog.models import Team

from products.tasks.backend.models import Task
from products.tasks.backend.services.sandbox import SandboxTemplate

from ..facade.enums import TaskType
from ..models import AutoMLPipeline

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


def enqueue_bootstrap_training(*, pipeline: AutoMLPipeline, user_id: int) -> Task:
    """Create a `Task` that will train the pipeline's first model in a sandbox.

    Returns the created `Task` so the caller can persist its id on the pipeline.
    Raises whatever `Task.create_and_run` raises (missing User, GitHub integration
    issues, etc.) — the caller is responsible for marking the pipeline FAILED on
    bubble-up.
    """
    team = Team.objects.get(id=pipeline.team_id)
    return Task.create_and_run(
        team=team,
        title=f"AutoML bootstrap: {pipeline.name}",
        description=_build_orchestration_brief(pipeline),
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


def _build_orchestration_brief(pipeline: AutoMLPipeline) -> str:
    """Build the task description handed to the bootstrap agent.

    The description is intentionally thin: a pointer to the
    ``automl-bootstrap`` skill (which carries the workflow, CLI reference,
    pitfalls, and recovery framework) plus the per-pipeline payload the agent
    consumes (spec, gates, training query). The skill is loaded by the
    agent's normal skill-discovery mechanism inside the sandbox.

    Keeping the dynamic content small keeps the prompt cheap and lets the
    skill evolve without rebuilding image artifacts or re-substituting
    Python templates.
    """
    spec_json = json.dumps(_build_pipeline_spec(pipeline), indent=2, default=str)
    gates_json = json.dumps(_build_gate_config(pipeline), indent=2, default=str)
    training_query = _extract_training_query(pipeline)

    return (
        f"# AutoML bootstrap: {pipeline.name}\n"
        "\n"
        "Run the `automl-bootstrap` skill. The skill carries the workflow, the\n"
        "`automl` CLI surface, the common-pitfalls catalog, and the failure-\n"
        "recovery framework. Iterate on recoverable errors; don't bail at the\n"
        "first non-zero exit.\n"
        "\n"
        "## Pipeline spec\n"
        "\n"
        "Treat every field as authoritative; do not edit the config.\n"
        "\n"
        "```json\n"
        f"{spec_json}\n"
        "```\n"
        "\n"
        "## Promotion gates\n"
        "\n"
        "Apply per step 5 of the skill. Bootstrap never auto-displaces an\n"
        "existing champion; see step 6 for the precondition check.\n"
        "\n"
        "```json\n"
        f"{gates_json}\n"
        "```\n"
        "\n"
        "## Training-population HogQL\n"
        "\n"
        "Write this to a file in step 2 (the skill shows the heredoc pattern).\n"
        "If `prepare-from-hogql` rejects it with a parse / type error, read\n"
        "the response body and fix the query — see the skill's common-pitfalls\n"
        "reference for known gotchas (especially `AND ... BETWEEN ...` precedence).\n"
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
