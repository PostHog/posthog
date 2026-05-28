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

import re
import json
import textwrap
from datetime import date

from django.utils import timezone as django_timezone

import structlog
from pydantic import BaseModel, Field, field_validator

from products.autoresearch.backend.labeling import NUM_FOLDS, _build_labeled_users_cte
from products.autoresearch.backend.models import AutoresearchPipeline, AutoresearchSuggestion, AutoresearchTrainingRun

# Static contract enforced on the agent's feature_sql to prevent the most common
# leakage patterns. See ModelRecipeOutput.feature_sql and the agent prompt for
# the full contract; this list is the machine-checked subset.
_FEATURE_SQL_ANCHORS_PLACEHOLDER = "{anchors}"
_FEATURE_SQL_CUTOFF_REFERENCE = "cutoff_ts"
# Match bare now() / now(0) / now(arg) — the leakage tell. Comments and string
# literals can false-positive here, but agents don't typically use now() inside
# strings; if they do, they can rephrase.
_FEATURE_SQL_NOW_RE = re.compile(r"\bnow\s*\(", re.IGNORECASE)


def _quote_for_inlined_sql(value: object) -> str:
    """
    Conservatively render a value for inlining into a SQL string the agent will
    paste into execute-sql. Only handles the value shapes labeling.py emits —
    target_event strings, numeric horizons/lookbacks, and population-filter
    primitives. Anything else falls through to a quoted string with embedded
    single quotes doubled (HogQL string literal escape).
    """
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float):
        return str(value)
    if value is None:
        return "NULL"
    text = str(value).replace("'", "''")
    return f"'{text}'"


def _resolve_labeled_anchors_cte_for_prompt(pipeline: AutoresearchPipeline) -> str:
    """
    Return the labeled_anchors CTE block as a ready-to-paste SQL string, with all
    placeholders inlined. The agent embeds this verbatim into its execute-sql
    queries to materialize labeled training data for its inner loop.

    Same labeling math the server runs at inference time (build_training_features_sql)
    so the agent's local eval is the trainer's actual training data — not a proxy.
    """
    cte, values = _build_labeled_users_cte(
        target_event=pipeline.target_event,
        horizon_days=pipeline.horizon_days,
        lookback_days=pipeline.training_lookback_days or 180,
        training_population=pipeline.training_population,
        sample_limit=None,
    )
    resolved = cte
    for key, val in values.items():
        resolved = resolved.replace("{" + key + "}", _quote_for_inlined_sql(val))

    return (
        resolved.rstrip()
        + ",\n        labeled_anchors AS (\n"
        + "            SELECT\n"
        + "                person_id,\n"
        + "                t0_ts,\n"
        + "                positive,\n"
        + f"                toInt(bitAnd(cityHash64(concat('fold:', toString(person_id))), 2147483647)) % {NUM_FOLDS} AS fold\n"
        + "            FROM labeled_users\n"
        + "        )"
    )


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
            "HogQL SELECT returning one row per anchor (person_id) with feature columns. "
            "MUST contain the literal placeholder `{anchors}` — the framework substitutes it with a "
            "per-user (person_id, cutoff_ts) table at runtime (per-user T0 during training; "
            "now() during inference). MUST filter events with `e.timestamp < fromUnixTimestamp(a.cutoff_ts)` "
            "to prevent label leakage. MUST NOT call `now()` directly — use `a.cutoff_ts` instead. "
            "Use {lookback_days} as a placeholder for the rolling-window size in days."
        )
    )
    feature_transforms: list[dict] = Field(
        default_factory=list,
        description="Optional preprocessing transforms (e.g. log scale, clipping). Usually empty.",
    )

    @field_validator("feature_sql")
    @classmethod
    def _feature_sql_contract(cls, value: str) -> str:
        """
        Enforce the leakage-prevention contract on feature_sql at submission time.
        Agents that violate the contract get a clear error from set_output and can
        retry within their iteration budget.
        """
        if _FEATURE_SQL_ANCHORS_PLACEHOLDER not in value:
            raise ValueError(
                f"feature_sql must contain the placeholder {_FEATURE_SQL_ANCHORS_PLACEHOLDER!r}. "
                "Select FROM {anchors} a (the framework-supplied per-user (person_id, cutoff_ts) "
                "table) and join events with `e.timestamp < fromUnixTimestamp(a.cutoff_ts)`. "
                "See the agent prompt's worked example."
            )
        if _FEATURE_SQL_CUTOFF_REFERENCE not in value:
            raise ValueError(
                "feature_sql must reference `cutoff_ts` (e.g. `e.timestamp < "
                "fromUnixTimestamp(a.cutoff_ts)`). Without this filter, features include events "
                "from the label window — direct leakage."
            )
        if _FEATURE_SQL_NOW_RE.search(value):
            raise ValueError(
                "feature_sql must not call `now()` — use `fromUnixTimestamp(a.cutoff_ts)` as the "
                "per-user cutoff. Calling `now()` breaks training (the cutoff varies per user) "
                "and silently leaks label-window data into features."
            )
        return value

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
    labeled_anchors_cte = _resolve_labeled_anchors_cte_for_prompt(pipeline)

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

        ## How labeling works (read this carefully — it shapes everything below)

        You do NOT compute labels yourself. PostHog runs a deterministic random-T0
        labeler that produces, for each user in the training population, exactly one
        labeled example:

          T0_user   = a per-user deterministic random point in their history
          label     = 1 if `{pipeline.target_event}` fires in [T0_user, T0_user + {pipeline.horizon_days}), else 0

        This means features for each user MUST be computed strictly as of THAT
        user's T0 — never using events from on/after T0_user. Otherwise the model
        peeks at the label window and the holdout AUC is fiction.

        At inference time the same feature SQL runs with cutoff_ts = now() per
        user. Train and inference become byte-identical operations on different
        anchor tables — that is the only way the holdout AUC means anything.

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

        Note: the base rate of the prediction task (random-T0 conversion rate)
        is already computed and shown to the user in the wizard — you don't need
        to estimate it yourself. If you want to sanity-check the data, query
        event volumes, not "did target fire in last N days" style proxies.

        ### Step 2 — Design feature SQL (the leakage-safe contract)

        Your feature SQL MUST follow this contract. Recipes that violate it are
        rejected at submission with a clear error — fix and resubmit within your
        iteration budget.

        **Hard rules:**

        1. Select `FROM {{anchors}} a` — the framework provides this table with
           columns `(person_id, cutoff_ts)`. At training cutoff_ts is per-user T0;
           at inference cutoff_ts = now(). Same SQL, two anchor tables.
        2. Join events with `e.timestamp < fromUnixTimestamp(a.cutoff_ts)` —
           strict `<`, not `<=`. This is the leakage guard. Any feature that
           reads events at or after cutoff_ts is invalid.
        3. Window the lookback against the cutoff:
           `e.timestamp >= fromUnixTimestamp(a.cutoff_ts) - toIntervalDay({{lookback_days}})`.
        4. Output `a.person_id AS distinct_id` as the first column.
        5. `GROUP BY a.person_id`.
        6. **Never** call `now()` in feature SQL — use `a.cutoff_ts` instead.
           The framework's static validator rejects `now()` outright.

        **Worked example:**

        ```sql
        SELECT
            a.person_id AS distinct_id,
            countIf(e.event = '$pageview') AS pageviews_in_window,
            countIf(e.event = 'uploaded_file') AS uploads_in_window,
            uniqIf(e.event, e.event NOT LIKE '$%') AS unique_user_events,
            dateDiff(
                'day',
                max(e.timestamp),
                fromUnixTimestamp(a.cutoff_ts)
            ) AS days_since_last_event
        FROM {{anchors}} a
        LEFT JOIN events e
            ON e.person_id = a.person_id
            AND e.timestamp <  fromUnixTimestamp(a.cutoff_ts)
            AND e.timestamp >= fromUnixTimestamp(a.cutoff_ts) - toIntervalDay({{lookback_days}})
        GROUP BY a.person_id
        ```

        Good features to consider:
        - Event count aggregates (`countIf(e.event = 'X')`)
        - Recency signals (`dateDiff('day', max(e.timestamp), fromUnixTimestamp(a.cutoff_ts))`)
        - Event diversity (`uniqIf(e.event, ...)`)
        - Property features if meaningful

        ### Step 3 — Fit and evaluate (in your sandbox)

        For each iteration, run one composite `execute-sql` query that returns one row
        per labeled user with feature columns + `__label` + `__fold`. Then fit sklearn
        locally on `__fold != 0` and evaluate on `__fold == 0`. This is the real
        holdout AUC — no proxies, no `corr()` shortcuts.

        **Paste-in `labeled_anchors` CTE for THIS pipeline** (uses your real
        horizon, training lookback, target event, and population filter):

        ```sql
        WITH {labeled_anchors_cte}
        ```

        **The composite query template you run each iteration:**

        ```sql
        WITH {labeled_anchors_cte}
        SELECT
            f.*,
            la.positive AS __label,
            la.fold AS __fold
        FROM (
            -- ↓↓↓ YOUR feature_sql, with {{anchors}} substituted with
            --     (SELECT person_id, t0_ts AS cutoff_ts FROM labeled_anchors)
            <your feature SQL>
        ) f
        LEFT JOIN labeled_anchors la ON f.distinct_id = la.person_id
        ```

        **The Python fit + eval pattern:**

        ```python
        import pandas as pd
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score

        # `rows` is whatever execute-sql returned for the composite query above.
        df = pd.DataFrame(rows)

        feature_cols = [c for c in df.columns if c not in ('distinct_id', '__label', '__fold')]
        X = df[feature_cols].fillna(0).astype(float)
        y = df['__label'].astype(int)
        fold = df['__fold'].astype(int)

        train, holdout = fold != 0, fold == 0
        if y[holdout].nunique() < 2 or y[train].sum() < 5:
            # Skip this iteration — not enough signal to fit/evaluate honestly.
            holdout_auc = None
        else:
            model = LogisticRegression(C=1.0, max_iter=200, random_state=42)
            model.fit(X[train], y[train])
            p_holdout = model.predict_proba(X[holdout])[:, 1]
            holdout_auc = float(roc_auc_score(y[holdout], p_holdout))
        ```

        **Recording each iteration:** call `autoresearch-training-runs-iterations-create`
        with the iteration's feature_sql, model_class, model_params, holdout_score (the
        AUC you just computed), and a one-line agent_description of what you tried.
        Status: `"kept"` if it beats your best so far, `"discarded"` otherwise.

        ### Step 4 — Iterate

        Try at least {min_iters} distinct feature hypotheses. Vary along axes that
        actually matter for predictive signal:
        - Which events you count (engagement, conversion-adjacent, friction)
        - Recency vs frequency (counts in last 7d vs 30d, time-since-last)
        - Cross-event ratios and diversity (uniqIf)
        - Property-conditioned counts (countIf with a property filter)

        Pick the iteration with the highest holdout AUC as your final submission.

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
            # "full" grants the agent autoresearch:write so it can record per-iteration
            # progress via autoresearch-training-runs-iterations-create. Read-only would
            # hide write tools and the iterations tab would stay empty.
            posthog_mcp_scopes="full",
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

        training_run.task_id = task.pk
        training_run.task_run_id = task_run.id
        training_run.save(update_fields=["task_id", "task_run_id"])

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
