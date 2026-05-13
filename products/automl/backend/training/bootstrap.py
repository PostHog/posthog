"""Enqueue bootstrap training tasks for AutoML pipelines.

Builds an orchestration brief + pipeline spec and hands them to the `tasks`
product via ``Task.create_and_run``. The real ML runs inside
``ProcessTaskWorkflow``'s sandbox — we just establish the bridge here. The
description is a stub for now; the frozen-harness contract lands in a
follow-up commit.
"""

from __future__ import annotations

import json
from typing import Any

from posthog.models import Team

from products.tasks.backend.models import Task

from ..models import AutoMLPipeline

# Placeholder orchestration brief. Replace with frozen-harness instructions once
# the real training contract (evaluator scripts, recipe template, AutoMLModelVersion
# persistence) lands. Keeping it terse so future diffs to this file show real intent
# changes.
_ORCHESTRATION_TEMPLATE = """\
# AutoML bootstrap: {pipeline_name}

You are the AutoML bootstrap agent. Your job is to train the first model for an
AutoML pipeline of task type `{task_type}`.

## Pipeline spec

```json
{spec_json}
```

## What to do (stub)

This is a placeholder description. The real training contract lands in a
follow-up commit. For now, acknowledge receipt of the spec and exit 0.

A future revision will:

1. Pull the latest feature recipe from PostHog (HogQL via the `execute-sql` MCP tool).
2. Run `products.automl.backend.training.trainer.train(...)` against a snapshot.
3. Persist the result via the AutoML facade's `record_training_result(...)`.
4. Promote the champion via `promote_to_champion(...)` once gates pass.
5. Emit predictions as `$automl_prediction` events.
"""


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
    """Build the markdown brief passed as the Task description."""
    spec_json = json.dumps(_build_pipeline_spec(pipeline), indent=2, default=str)
    return _ORCHESTRATION_TEMPLATE.format(
        pipeline_name=pipeline.name,
        task_type=pipeline.task_type,
        spec_json=spec_json,
    )


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
