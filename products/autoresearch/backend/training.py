"""
Real sandbox training: launches the autoresearch agent loop in a PostHog Task sandbox.

The agent explores correlations in the team's event data using HogQL, iterates on
feature sets and model configs, and submits its best recipe as structured JSON via the
set_output API endpoint. Recipe ingestion runs after TaskRun completion (see
training_ingestion.py for the signal handler).

Flow:
  1. run_training() creates an AutoresearchTrainingRun (status=RUNNING) and fires
     Task.create_and_run() with internal=True, no repository, output_schema set.
  2. The sandbox agent receives the description, runs the research loop, and calls
     POST /api/projects/.../task-runs/$POSTHOG_RESUME_RUN_ID/set_output/ with the recipe.
  3. The post_save signal on TaskRun (registered in apps.py → training_ingestion.py)
     detects completion and ingests the recipe into AutoresearchModel.
"""

from __future__ import annotations

import json
import textwrap
from datetime import date

from django.utils import timezone as django_timezone

import structlog
from pydantic import BaseModel, Field

from products.autoresearch.backend.models import AutoresearchPipeline, AutoresearchSuggestion, AutoresearchTrainingRun

logger = structlog.get_logger(__name__)


# ── Pydantic output schema (also used in training_ingestion.py) ───────────────


class IterationRecord(BaseModel):
    iteration_number: int = Field(description="1-based iteration counter")
    recipe_hash: str = Field(description="SHA-256 of the serialized recipe JSON for this iteration")
    model_class: str = Field(description="sklearn model class, e.g. sklearn.linear_model.LogisticRegression")
    model_params: dict = Field(description="Hyperparameters used in this iteration")
    feature_summary: str = Field(description="Brief description of the features tried in this iteration")
    holdout_score: float = Field(ge=0.0, le=1.0, description="Estimated holdout AUC (0–1)")
    status: str = Field(description="'kept' if this recipe was carried forward, 'discarded' otherwise")
    agent_description: str = Field(description="Why this iteration was kept or discarded")


class ModelFeatureImportance(BaseModel):
    name: str = Field(description="Feature column name")
    importance: float = Field(ge=0.0, description="Relative importance weight (higher is more important)")
    direction: str = Field(description="'positive' or 'negative' impact on predicted probability")


class ModelExplanation(BaseModel):
    top_features: list[ModelFeatureImportance] = Field(
        description="Top feature importances sorted by importance descending"
    )


class ModelRecipeOutput(BaseModel):
    feature_sql: str = Field(
        description=(
            "HogQL SELECT returning one row per person_id with feature columns. "
            "Use {lookback_days} as a placeholder for the rolling-window size in days."
        )
    )
    feature_transforms: list[dict] = Field(
        default_factory=list,
        description="Optional preprocessing transforms (e.g. log scale, clipping). Usually empty.",
    )
    model_class: str = Field(
        default="sklearn.linear_model.LogisticRegression",
        description="sklearn model class path, e.g. sklearn.linear_model.LogisticRegression",
    )
    model_params: dict = Field(description="Hyperparameters for model_class, e.g. {C: 1.0, max_iter: 200}")
    fit_signature: str = Field(
        description="SHA-256 of (feature_sql + model_class + JSON-serialized model_params). Deduplication key."
    )
    trained_on: str = Field(description="Date range of training data, e.g. '2026-04-01 to 2026-05-01'")
    holdout_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Estimated holdout AUC (0–1). Be honest — validated against realized outcomes later.",
    )
    agent_description: str = Field(
        description="Plain-English summary of feature choices and why this recipe was selected"
    )
    model_explanation: ModelExplanation = Field(description="Top feature importances with direction of effect")
    iterations: list[IterationRecord] = Field(
        default_factory=list,
        description="One record per iteration attempted (both kept and discarded).",
    )


# ── Agent prompt ───────────────────────────────────────────────────────────────


def build_agent_description(
    pipeline: AutoresearchPipeline,
    iteration_budget: int,
    pending_suggestions: list[AutoresearchSuggestion] | None = None,
) -> str:
    """Build the Claude Code agent prompt for the autoresearch training loop."""
    pop_clause = ""
    if pipeline.training_population:
        pop_clause = f"\n- **Training population filter**: `{json.dumps(pipeline.training_population)}`"

    schema_json = json.dumps(ModelRecipeOutput.model_json_schema(), indent=2)
    today_iso = date.today().isoformat()
    min_iters = min(3, iteration_budget)

    prompt = textwrap.dedent(f"""
        # PostHog Autoresearch Agent

        Your goal is to discover predictive features for a prediction pipeline and output a
        portable model recipe as structured JSON.

        ## Pipeline specification

        - **Target event**: `{pipeline.target_event}`
        - **Prediction horizon**: {pipeline.horizon_days} days
        - **Output person property**: `{pipeline.output_person_property}`
        - **Iteration budget**: {iteration_budget}{pop_clause}
        - **Today's date**: {today_iso}

        ## Step 0 — Load live pipeline context (do this first, before any SQL)

        Pipeline ID: `{pipeline.pk}`

        1. **Find the champion model**: call `autoresearch-models-list` with `pipeline_id = "{pipeline.pk}"`.
           Look for an entry with `role = "champion"`. Note its `id` and `holdout_score`.

        2. **Load the champion recipe** (if a champion exists): call `autoresearch-models-retrieve`
           with the champion `id`. Read `model_recipe.feature_sql` — this is the current best
           feature set. Your primary goal is to produce a recipe that beats `holdout_score`.
           Start from a meaningfully different hypothesis, not a trivial variant.

        3. **Review training history**: call `autoresearch-training-runs-list` with `pipeline_id = "{pipeline.pk}"`.
           Check `best_holdout_score` and `iteration_count` from prior runs to avoid repeating
           approaches that were already tried and discarded.

        If no champion exists you are establishing the baseline — aim for AUC > 0.6.

        ## Research loop (perform at least {min_iters} iterations)

        ### Step 1 — Explore the data

        Use the PostHog `execute-sql` MCP tool to understand what's available:

        ```sql
        -- What events exist and how often?
        SELECT event, count() AS cnt
        FROM events
        WHERE timestamp >= now() - toIntervalDay(30)
        GROUP BY event ORDER BY cnt DESC LIMIT 30
        ```

        ```sql
        -- What fraction of users trigger the target event within the horizon?
        SELECT
            countDistinct(person_id) AS total_users,
            countDistinctIf(person_id, event = '{pipeline.target_event}') AS positive_users,
            positive_users / total_users AS base_rate
        FROM events
        WHERE timestamp >= now() - toIntervalDay(90)
        ```

        ### Step 2 — Build a binary label

        Identify users who performed `{pipeline.target_event}` within {pipeline.horizon_days} days
        after a reference date. Use a 90-day lookback as your training window.

        ### Step 3 — Design feature SQL

        Write a HogQL SELECT returning **one row per person_id** with feature columns.
        Good features:
        - Event count aggregates (`countIf(event = 'X' AND ...)`)
        - Recency signals (`dateDiff('day', max(timestamp), today())`)
        - Event diversity (`uniqIf(event, ...)`)
        - Property features if meaningful

        Rules:
        - Always: `person_id AS distinct_id` as the first column
        - Always: `GROUP BY person_id`
        - Use `{{lookback_days}}` as a placeholder for the rolling window (integer days)
        - Query must run against the `events` table

        ### Step 4 — Estimate quality

        Use ClickHouse `corr()` to measure point-biserial correlation between each feature
        and the binary label. Estimate AUC ≈ 0.5 + 0.25 × Σ|corr_i| (cap at 0.95).

        ### Step 5 — Iterate

        Try at least {min_iters} distinct feature sets. Compare estimated AUCs.
        Choose the best recipe for the final output.

        ## Submitting your recipe

        When you have finished iterating, write your recipe to `recipe.json` and submit it:

        ```bash
        # Write the recipe JSON to a file first
        cat > recipe.json << 'RECIPE_EOF'
        {{
          "feature_sql": "SELECT person_id AS distinct_id, ... FROM events ...",
          ...
        }}
        RECIPE_EOF

        # Validate it parses correctly
        python3 -c "import json; json.load(open('recipe.json')); print('OK')"

        # Submit to PostHog
        curl -s -X POST \\
          -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \\
          -H "Content-Type: application/json" \\
          -d "$(cat recipe.json)" \\
          "$POSTHOG_API_URL/api/projects/$POSTHOG_PROJECT_ID/task-runs/$POSTHOG_RESUME_RUN_ID/set_output/"
        ```

        A `200` response means success. A non-200 response means the JSON didn't match the
        required schema — check the error message and fix your recipe.json.

        ## Required output schema

        Your `recipe.json` MUST match this JSON schema exactly:

        ```json
        {schema_json}
        ```

        **Honesty note**: `holdout_score` is validated against realized outcomes after inference.
        An AUC of 0.55 that reflects real data beats a fabricated 0.80.
    """).strip()

    if pending_suggestions:  # noqa: SIM102
        lines = [
            "",
            "",
            "## Pending suggestions",
            "",
            "The following suggestions have been queued by users or agents. At the start of your",
            "first iteration, decide for each:",
            "- **Translate to a recipe** — spawn one or more iterations. Set status to acted_on.",
            "- **Apply as a constraint** — use as context across your iterations. Set status to picked_up.",
            "- **Reject** — violates a guardrail or is irrelevant. Set status to dismissed with rationale.",
            "",
            "For each suggestion you act on, include a brief `agent_response` in your recipe output's",
            "`agent_description` field explaining how you interpreted it.",
            "",
        ]
        for s in pending_suggestions:
            priority_label = "TRY NEXT" if s.priority == AutoresearchSuggestion.Priority.TRY_NEXT else "Consider"
            lines.append(f"[{priority_label}] (ID: {s.pk}) {s.prompt}")
        prompt += "\n" + "\n".join(lines)

    return prompt


# ── Main entry point ──────────────────────────────────────────────────────────


def run_training(
    pipeline: AutoresearchPipeline,
    iteration_budget: int,
    user_id: int | None,
) -> AutoresearchTrainingRun:
    """
    Launch a real agent sandbox training run.

    Creates an AutoresearchTrainingRun (status=RUNNING) and fires Task.create_and_run()
    to start the autoresearch agent. Returns the training run immediately; recipe
    ingestion happens asynchronously when the TaskRun completes.

    Raises if Temporal is unreachable or the task cannot be created.
    """
    from products.tasks.backend.models import Task, TaskRun

    now = django_timezone.now()
    training_run = AutoresearchTrainingRun.objects.create(
        pipeline=pipeline,
        status=AutoresearchTrainingRun.Status.RUNNING,
        iteration_budget=iteration_budget,
        started_at=now,
    )

    try:
        pending_suggestions = list(
            AutoresearchSuggestion.objects.filter(
                pipeline=pipeline,
                status=AutoresearchSuggestion.Status.QUEUED,
            ).order_by("-priority", "created_at")
        )
        description = build_agent_description(
            pipeline=pipeline,
            iteration_budget=iteration_budget,
            pending_suggestions=pending_suggestions or None,
        )

        task = Task.create_and_run(
            team=pipeline.team,
            title=f"[autoresearch] {pipeline.name}: learn to predict '{pipeline.target_event}'",
            description=description,
            origin_product=Task.OriginProduct.AUTORESEARCH,
            user_id=user_id,
            repository=None,
            create_pr=False,
            mode="background",
            internal=True,
            output_schema=ModelRecipeOutput,
            posthog_mcp_scopes="read_only",  # INTERNAL_SCOPES already adds task:write
        )

        task_run = task.latest_run
        if not task_run:
            raise RuntimeError("Task.create_and_run() did not produce a TaskRun")

        # Embed the training_run_id in the TaskRun state so the completion
        # signal handler can look it up without an extra DB query.
        TaskRun.update_state_atomic(
            run_id=task_run.id,
            updates={"autoresearch_training_run_id": str(training_run.id)},
        )

        training_run.task_run_id = task_run.id
        training_run.save(update_fields=["task_run_id"])

        logger.info(
            "autoresearch_training_started",
            pipeline_id=str(pipeline.pk),
            training_run_id=str(training_run.pk),
            task_id=str(task.pk),
            task_run_id=str(task_run.id),
        )
        return training_run

    except Exception:
        training_run.status = AutoresearchTrainingRun.Status.FAILED
        training_run.completed_at = django_timezone.now()
        training_run.error = "Failed to launch training task"
        training_run.save(update_fields=["status", "completed_at", "error"])
        logger.exception("autoresearch_training_launch_failed", pipeline_id=str(pipeline.pk))
        raise
