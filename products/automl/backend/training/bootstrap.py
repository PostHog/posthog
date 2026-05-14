"""Enqueue bootstrap training tasks for AutoML pipelines.

Builds an orchestration brief + pipeline spec and hands them to the `tasks`
product via ``Task.create_and_run``. The real ML runs inside
``ProcessTaskWorkflow``'s sandbox; this module is just the bridge that
constructs the prompt and the spec the agent operates on.

The brief itself lives in ``bootstrap_brief.md`` (alongside this file) so the
prose stays editable without wrestling Python triple-quoted escapes.
"""

from __future__ import annotations

import json
from pathlib import Path
from string import Template
from typing import Any

from posthog.models import Team

from products.tasks.backend.models import Task

from ..facade.enums import TaskType
from ..models import AutoMLPipeline

# Where the markdown template lives. Loaded fresh per call so edits to the
# brief don't require restarting any long-lived process during development.
_BRIEF_TEMPLATE_PATH = Path(__file__).parent / "bootstrap_brief.md"


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
    )


def _build_orchestration_brief(pipeline: AutoMLPipeline) -> str:
    """Build the markdown brief passed as the Task description.

    Uses ``string.Template`` substitution rather than ``str.format`` so JSON
    code samples in the brief (which contain literal ``{`` / ``}``) don't
    require escaping. Substitution keys use ``$placeholder``; literal ``$``
    in the template is ``$$``.
    """
    template = Template(_BRIEF_TEMPLATE_PATH.read_text(encoding="utf-8"))
    spec_json = json.dumps(_build_pipeline_spec(pipeline), indent=2, default=str)
    gates_json = json.dumps(_build_gate_config(pipeline), indent=2, default=str)
    return template.substitute(
        pipeline_name=pipeline.name,
        task_type=pipeline.task_type,
        pipeline_spec=spec_json,
        gates=gates_json,
        # Inlined so the agent doesn't have to parse JSON to recover the HogQL
        # in step 2's heredoc. Falls back to an empty string when the population
        # isn't a HogQL kind — the agent will hit `snapshot_fetch_failed` in
        # that case, which is the right failure mode.
        training_query=_extract_training_query(pipeline),
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
