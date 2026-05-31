"""
Real sandbox training: launches the autoresearch agent loop in a PostHog Task sandbox.

The agent explores the team's event data with HogQL, iterates on feature sets and models
in-sandbox, and authors a runnable bundle (features.sql / train.py / predict.py /
recipe.yml) that it uploads via the autoresearch MCP write tools.

Flow:
  1. run_training() creates an AutoresearchTrainingRun (status=RUNNING) and fires
     Task.create_and_run() with internal=True, no repository.
  2. The sandbox agent records each iteration (autoresearch-training-runs-iterations-create),
     uploads the winning bundle (autoresearch-training-runs-artifacts-upload-create), and
     finalizes the run (autoresearch-training-runs-complete-create), which selects the
     champion via the promotion ladder and attaches the bundle as its artifact.
  3. If the agent ends without finalizing, the post_save signal on TaskRun (apps.py →
     training_ingestion.handle_task_run_completed) finalizes any recorded iterations, or
     marks the run failed if none.
"""

from __future__ import annotations

import json
import textwrap
from datetime import date

from django.utils import timezone as django_timezone

import structlog

from products.autoresearch.backend.labeling import NUM_FOLDS, _build_labeled_users_cte
from products.autoresearch.backend.models import AutoresearchPipeline, AutoresearchSuggestion, AutoresearchTrainingRun


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


# ── Agent prompt ───────────────────────────────────────────────────────────────


def build_agent_description(
    pipeline: AutoresearchPipeline,
    iteration_budget: int,
    training_run_id: str,
    pending_suggestions: list[AutoresearchSuggestion] | None = None,
) -> str:
    """Build the Claude Code agent prompt for the autoresearch training loop."""
    pop_clause = ""
    if pipeline.training_population:
        pop_clause = f"\n- **Training population filter**: `{json.dumps(pipeline.training_population)}`"

    today_iso = date.today().isoformat()
    min_iters = min(3, iteration_budget)
    labeled_anchors_cte = _resolve_labeled_anchors_cte_for_prompt(pipeline)

    prompt = textwrap.dedent(f"""
        # PostHog Autoresearch Agent

        Your goal is to discover predictive features for a prediction pipeline and author a
        **runnable model bundle** — four files the framework runs in a sandbox to score users
        daily. You do NOT emit a JSON recipe and you do NOT call set_output. You upload the
        bundle files through MCP tools and finalize the run.

        ## Pipeline specification

        - **Target event**: `{pipeline.target_event}`
        - **Prediction horizon**: {pipeline.horizon_days} days
        - **Output person property**: `{pipeline.output_person_property}`
        - **Iteration budget**: {iteration_budget}{pop_clause}
        - **Today's date**: {today_iso}

        ## Identifiers for every tool call

        - **Pipeline ID**: `{pipeline.pk}` (pass as `pipeline_id`)
        - **Training run ID**: `{training_run_id}` (pass as `id` to the training-runs tools)

        The training run is already open. Record iterations against it, upload the bundle to
        it, then complete it — all via the `autoresearch-training-runs-*` tools using the two
        IDs above.

        ## Step 0 — Load live pipeline context (do this first, before any SQL)

        1. **Find the champion model**: call `autoresearch-models-list` with `pipeline_id = "{pipeline.pk}"`.
           Look for `role = "champion"`. Note its `id`, `holdout_score`, and `source_training_run`.

        2. **Load the champion's bundle** (if one exists): call `autoresearch-models-retrieve`
           on the champion `id`. If it has a `source_training_run`, pull its prior code as a
           starting point — call `autoresearch-training-runs-artifacts-get-create` with
           `id = "<source_training_run>"`, `path = "features.sql"` (and `train.py`). Your goal is
           to beat `holdout_score`. Start from a meaningfully different hypothesis, not a trivial variant.

        3. **Review training history**: call `autoresearch-training-runs-list` with `pipeline_id = "{pipeline.pk}"`.
           Check `best_holdout_score` and `iteration_count` to avoid repeating discarded approaches.

        If no champion exists you are establishing the baseline — aim for AUC > 0.6.

        ## How labeling works (read this carefully — it shapes everything below)

        You do NOT compute labels yourself. PostHog runs a deterministic random-T0
        labeler that produces, for each user in the training population, exactly one
        labeled example:

          T0_user   = a per-user deterministic random point in their history
          label     = 1 if `{pipeline.target_event}` fires in [T0_user, T0_user + {pipeline.horizon_days}), else 0

        Features for each user MUST be computed strictly as of THAT user's T0 — never
        using events on/after T0_user, or the model peeks at the label window and the
        holdout AUC is fiction.

        At inference time the framework runs the SAME `features.sql` with cutoff_ts = now()
        per user, re-fits `train.py` on fresh data, and scores with `predict.py`. Train and
        inference are byte-identical operations on different anchor tables — that is the only
        way the holdout AUC means anything. Leakage vigilance is YOUR job: if a feature looks
        too predictive, suspect it reads the label window and fix it.

        ## The bundle you will produce

        Four files, uploaded via `autoresearch-training-runs-artifacts-upload-create` (one call
        per file, contents base64-encoded in `content_base64`):

        | path           | what it is                                                            |
        |----------------|-----------------------------------------------------------------------|
        | `features.sql` | HogQL feature query with `{{anchors}}` + `{{lookback_days}}` placeholders |
        | `train.py`     | standalone sklearn fit script (any model you like inside)             |
        | `predict.py`   | standalone scoring script                                            |
        | `recipe.yml`   | informational metadata for the model card                            |

        The framework runs train.py + predict.py in a locked-down sandbox with NO network and
        NO credentials. `NOTEBOOK_BASE` ships pandas / numpy / scikit-learn — import only those.

        ## Research loop (perform at least {min_iters} iterations)

        ### Step 1 — Explore the data

        Use the `execute-sql` MCP tool to see what events exist:

        ```sql
        SELECT event, count() AS cnt
        FROM events
        WHERE timestamp >= now() - toIntervalDay(30)
        GROUP BY event ORDER BY cnt DESC LIMIT 30
        ```

        The base rate is already shown to the user in the wizard — don't estimate it. Sanity-check
        with event-volume queries, not "did target fire in last N days" proxies.

        ### Step 2 — Design `features.sql` (the leakage-safe contract)

        **Hard rules:**

        1. Select `FROM {{anchors}} a` — the framework supplies columns `(person_id, cutoff_ts)`.
           At training cutoff_ts is per-user T0; at inference cutoff_ts = now(). Same SQL, two tables.
        2. Join events with `e.timestamp < fromUnixTimestamp(a.cutoff_ts)` — strict `<`. The leakage guard.
        3. Window the lookback: `e.timestamp >= fromUnixTimestamp(a.cutoff_ts) - toIntervalDay({{lookback_days}})`.
        4. Output `a.person_id AS distinct_id` as the first column.
        5. `GROUP BY a.person_id, a.cutoff_ts` — ClickHouse needs cutoff_ts in the GROUP BY to
           select it (no Postgres-style functional-dependency inference). Still one row per person.
        6. **Never** call `now()` — use `a.cutoff_ts`. The framework rejects `now()` outright.
        7. Keep `{{anchors}}` and `{{lookback_days}}` OUT of SQL comments — the framework string-
           substitutes them everywhere, and a multi-line substitution inside a `--` comment breaks the parse.

        **Worked `features.sql` (a correct, runnable starting point):**

        ```sql
        SELECT
            a.person_id AS distinct_id,
            count(e.uuid) AS events_total,
            uniqIf(e.event, e.event NOT LIKE '$%') AS unique_user_events,
            countIf(e.event = '$pageview') AS pageviews,
            countIf(e.event = 'uploaded_file') AS uploads,
            dateDiff('day', max(e.timestamp), fromUnixTimestamp(a.cutoff_ts)) AS days_since_last_event
        FROM {{anchors}} a
        LEFT JOIN events e
            ON e.person_id = a.person_id
            AND e.timestamp <  fromUnixTimestamp(a.cutoff_ts)
            AND e.timestamp >= fromUnixTimestamp(a.cutoff_ts) - toIntervalDay({{lookback_days}})
        GROUP BY a.person_id, a.cutoff_ts
        ```

        ### Step 3 — Fit and evaluate (in your sandbox)

        For each iteration, run one composite `execute-sql` query returning one row per labeled
        user with feature columns + `__label` + `__fold`, then fit on `__fold != 0` and evaluate
        on `__fold == 0`. This is the real holdout AUC — no proxies.

        **Paste-in `labeled_anchors` CTE for THIS pipeline:**

        ```sql
        WITH {labeled_anchors_cte}
        ```

        **Composite query each iteration** (substitute `{{anchors}}` with
        `(SELECT person_id, t0_ts AS cutoff_ts FROM labeled_anchors)` and `{{lookback_days}}` with
        an integer, e.g. {max(30, pipeline.horizon_days * 4)}):

        ```sql
        WITH {labeled_anchors_cte}
        SELECT f.*, la.positive AS __label, la.fold AS __fold
        FROM ( <your features.sql, placeholders substituted> ) f
        LEFT JOIN labeled_anchors la ON f.distinct_id = la.person_id
        ```

        **Python fit + eval pattern:**

        ```python
        import pandas as pd
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score

        df = pd.DataFrame(rows)  # rows = execute-sql output for the composite query
        feature_cols = [c for c in df.columns if c not in ('distinct_id', '__label', '__fold')]
        X = df[feature_cols].fillna(0).astype(float)
        y = df['__label'].astype(int)
        fold = df['__fold'].astype(int)
        train, holdout = fold != 0, fold == 0
        if y[holdout].nunique() < 2 or y[train].sum() < 5:
            holdout_auc = None  # not enough signal — skip
        else:
            model = LogisticRegression(C=1.0, max_iter=200, random_state=42)
            model.fit(X[train], y[train])
            holdout_auc = float(roc_auc_score(y[holdout], model.predict_proba(X[holdout])[:, 1]))
        ```

        **Record each iteration:** call `autoresearch-training-runs-iterations-create` with
        `pipeline_id = "{pipeline.pk}"`, `id = "{training_run_id}"`, the iteration_number,
        recipe_snapshot (`{{"feature_sql": "..."}}`), model_spec (`{{"model_class": "...", "model_params": {{...}}}}`),
        holdout_score (the AUC you computed), status (`"kept"` if it beats your best so far, else `"discarded"`),
        and a one-line agent_description. These drive champion selection at completion.

        ### Step 4 — Iterate

        Try at least {min_iters} distinct hypotheses — vary which events you count, recency vs
        frequency, cross-event ratios/diversity, property-conditioned counts. Pick the highest
        holdout AUC as your winner.

        ## Author and upload the winning bundle

        Write the four files so they run STANDALONE in the sandbox under these exact CLI
        contracts, then upload each with `autoresearch-training-runs-artifacts-upload-create`
        (`pipeline_id = "{pipeline.pk}"`, `id = "{training_run_id}"`, `path`, `content_base64`).

        Data is exchanged as **parquet** (the sandbox ships pyarrow) — use
        `pd.read_parquet` / `DataFrame.to_parquet`, never `read_csv` / `to_csv`.

        **train.py** — invoked as:

        ```
        python train.py <train_features.parquet> <train_labels.parquet> <model.pkl> <output.json> \\
                        <holdout_features.parquet> <holdout_labels.parquet> --random-state 42
        ```

        - Features parquet: first column `distinct_id`, rest numeric. Labels parquet: `distinct_id`, `__label` (0/1).
        - Merge features⋈labels on `distinct_id`, fit your model on train, pickle
          `{{"model": ..., "feature_cols": [...]}}` to `<model.pkl>` (pin `random_state` from the arg).
        - Write `<output.json>`: `{{"holdout_auc": <float|null>, "n_train": <int>, "n_features": <int>}}`.
          The framework reads this FILE — print nothing structured to stdout. Exit non-zero on degenerate data.

        **predict.py** — invoked as:

        ```
        python predict.py <score_features.parquet> <model.pkl> <scores.parquet>
        ```

        - Load the pickle, align score features to `feature_cols` (missing → 0), write `<scores.parquet>`
          with columns `distinct_id,p_y`. Print NOTHING to stdout — the framework reads scores.parquet back.

        **Reference `train.py`** (edit the model; keep the I/O contract exactly):

        ```python
        import sys, json, pickle, argparse
        import pandas as pd
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score

        def load_xy(fpath, lpath):
            f = pd.read_parquet(fpath); l = pd.read_parquet(lpath)
            m = f.merge(l[["distinct_id", "__label"]], on="distinct_id", how="inner")
            cols = [c for c in f.columns if c != "distinct_id"]
            return pd.DataFrame(m[cols]).fillna(0).astype(float), pd.Series(m["__label"]).fillna(0).astype(int), cols

        p = argparse.ArgumentParser()
        for a in ["train_features","train_labels","model_out","output_json","holdout_features","holdout_labels"]:
            p.add_argument(a, nargs="?" if "holdout" in a else None)
        p.add_argument("--random-state", type=int, default=42)
        args = p.parse_args()

        Xtr, ytr, cols = load_xy(args.train_features, args.train_labels)
        if int(ytr.sum()) < 5 or int(len(ytr) - ytr.sum()) < 5:
            print("degenerate training data", file=sys.stderr); sys.exit(1)
        model = LogisticRegression(C=1.0, max_iter=200, random_state=args.random_state)
        model.fit(Xtr.to_numpy(), ytr.to_numpy())
        pickle.dump({{"model": model, "feature_cols": cols}}, open(args.model_out, "wb"))

        auc = None
        if args.holdout_features and args.holdout_labels:
            Xh, yh, _ = load_xy(args.holdout_features, args.holdout_labels)
            if len(Xh) and yh.nunique() >= 2:
                Xh = Xh.reindex(columns=cols, fill_value=0)
                auc = float(roc_auc_score(yh.to_numpy(), model.predict_proba(Xh.to_numpy())[:, 1]))
        json.dump({{"holdout_auc": round(auc,4) if auc is not None else None,
                   "n_train": int(len(ytr)), "n_features": len(cols)}}, open(args.output_json, "w"))
        ```

        **Reference `predict.py`** (keep exactly; it just applies the model):

        ```python
        import sys, pickle
        import pandas as pd
        score_path, model_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
        b = pickle.load(open(model_path, "rb"))
        f = pd.read_parquet(score_path)
        X = f.reindex(columns=b["feature_cols"], fill_value=0).fillna(0).astype(float)
        p = b["model"].predict_proba(X.to_numpy())[:, 1]
        pd.DataFrame({{"distinct_id": f["distinct_id"], "p_y": p.round(6)}}).to_parquet(out_path, index=False)
        ```

        **recipe.yml** — informational metadata for the model card. Example:

        ```yaml
        model_class: sklearn.linear_model.LogisticRegression
        model_params: {{C: 1.0, max_iter: 200, random_state: 42}}
        features:
            source_sql: features.sql
            description: <one line on your feature set>
        agent:
            description: <what you tried, what won, top features and why>
        ```

        ## Finalize

        When all four files are uploaded for the winning iteration:

        1. (Optional) confirm with `autoresearch-training-runs-artifacts-retrieve` that
           features.sql, train.py, predict.py, and recipe.yml are all present.
        2. Call `autoresearch-training-runs-complete-create` with `pipeline_id = "{pipeline.pk}"`
           and `id = "{training_run_id}"`. The backend picks the best iteration, decides
           champion vs challenger, and attaches your uploaded bundle as the model's artifact.

        **Honesty note**: holdout_auc is checked against realized outcomes after inference. An
        AUC of 0.55 that reflects real data beats a fabricated 0.80 — the realized gate is unfakeable.
    """).strip()

    if pending_suggestions:  # noqa: SIM102
        lines = [
            "",
            "",
            "## Pending suggestions",
            "",
            "The following suggestions have been queued by users or agents. At the start of your",
            "first iteration, decide for each:",
            "- **Translate to an iteration** — spawn one or more iterations. Set status to acted_on.",
            "- **Apply as a constraint** — use as context across your iterations. Set status to picked_up.",
            "- **Reject** — violates a guardrail or is irrelevant. Set status to dismissed with rationale.",
            "",
            "For each suggestion you act on, note how you interpreted it in the relevant iteration's",
            "agent_description and in recipe.yml's agent.description.",
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
            training_run_id=str(training_run.id),
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
            # "full" grants the agent autoresearch:write so it can record iterations via
            # autoresearch-training-runs-iterations-create, upload its bundle via
            # autoresearch-training-runs-artifacts-upload-create, and finalize via
            # autoresearch-training-runs-complete-create. Read-only would hide those tools.
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
