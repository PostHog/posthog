"""
Real sandbox training: launches the autoresearch agent loop in a PostHog Task sandbox.

The agent explores the team's event data with HogQL, iterates on feature sets and models
in-sandbox, and authors a runnable bundle (features.sql / train.py / predict.py) that it
uploads via the autoresearch MCP write tools.

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

from posthog.hogql.property import action_to_expr

from products.actions.backend.models.action import Action
from products.autoresearch.backend.models import AutoresearchPipeline, AutoresearchSuggestion, AutoresearchTrainingRun

logger = structlog.get_logger(__name__)


# ── Agent prompt ───────────────────────────────────────────────────────────────


def _describe_target(pipeline: AutoresearchPipeline) -> tuple[str, str]:
    """
    Describe the prediction target for the agent prompt, returning
    (spec_line, inline_ref).

    spec_line is the verbose "## Pipeline specification" bullet; inline_ref is the
    short phrase reused where the prompt talks about the label firing. Action
    targets spell out the underlying HogQL matcher so the agent knows exactly which
    rows count as positive — it can't see the label SQL otherwise.
    """
    definition = pipeline.target_definition or {}
    if definition.get("type") == "action":
        action_id = definition.get("action_id")
        try:
            action = Action.objects.get(id=action_id, team=pipeline.team)
            matcher = action_to_expr(action).to_hogql()
            spec_line = (
                f"action `{action.name}` (action_id {action_id}). "
                f"An events-table row counts as the target when it matches: `{matcher}`"
            )
            inline_ref = f"the action `{action.name}`"
            return spec_line, inline_ref
        except Action.DoesNotExist:
            logger.warning("autoresearch_target_action_missing", pipeline_id=str(pipeline.pk), action_id=action_id)
    return f"event `{pipeline.target_event}`", f"`{pipeline.target_event}`"


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
    target_spec_line, target_inline_ref = _describe_target(pipeline)

    prompt = textwrap.dedent(f"""
        # PostHog Autoresearch Agent

        Your goal is to discover predictive features for a prediction pipeline and author a
        **runnable model bundle** — four files the framework runs in a sandbox to score users
        daily. You do NOT emit a JSON recipe and you do NOT call set_output. You upload the
        bundle files through MCP tools and finalize the run.

        ## Pipeline specification

        - **Target**: {target_spec_line}
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

        3. **Read prior runs' learning memory**: call `autoresearch-training-runs-history` with
           `pipeline_id = "{pipeline.pk}"`. This returns recent completed runs — this pipeline first,
           then same-target sibling pipelines on the team. For each run, read its `summary` FIRST
           (the cheap orientation): `distillation` (what that run learned), `recommended_next` (what
           it suggested trying next), the `kept_ladder` (winning approaches), and `dead_ends`
           (approaches that did not help). Then, if a summary points somewhere worth it, drill into
           that run's full `iterations` trail (`agent_description`, `holdout_score`, status,
           `model_spec`). Mine all this before you iterate: reuse the features and transforms that
           won, act on a prior `recommended_next` when sensible, and do NOT re-try approaches already
           in `dead_ends`. In each iteration's `agent_description`, cite which prior learning you are
           building on or deliberately avoiding.

        If no champion exists you are establishing the baseline — aim for AUC > 0.6.

        ## How labeling works (read this carefully — it shapes everything below)

        You do NOT compute labels yourself. PostHog runs a deterministic random-T0
        labeler that produces, for each user in the training population, exactly one
        labeled example:

          T0_user   = a per-user deterministic random point in their history
          label     = 1 if {target_inline_ref} fires in [T0_user, T0_user + {pipeline.horizon_days}), else 0

        Features for each user MUST be computed strictly as of THAT user's T0 — never
        using events on/after T0_user, or the model peeks at the label window and the
        holdout AUC is fiction.

        At inference time the framework runs the SAME `features.sql` with cutoff_ts = now()
        per user, re-fits `train.py` on fresh data, and scores with `predict.py`. Train and
        inference are byte-identical operations on different anchor tables — that is the only
        way the holdout AUC means anything. Leakage vigilance is YOUR job: if a feature looks
        too predictive, suspect it reads the label window and fix it.

        ## The bundle you will produce

        Three files, uploaded via `autoresearch-training-runs-artifacts-upload-create` (one call
        per file, contents base64-encoded in `content_base64`):

        | path           | what it is                                                            |
        |----------------|-----------------------------------------------------------------------|
        | `features.sql` | HogQL feature query with `{{anchors}}` + `{{lookback_days}}` placeholders |
        | `train.py`     | standalone sklearn fit script (any model you like inside)             |
        | `predict.py`   | standalone scoring script                                            |

        The framework runs train.py + predict.py in a locked-down sandbox with NO network and
        NO credentials. It ships pandas / numpy / scikit-learn / pyarrow (the same libraries your
        own sandbox already has) — `import` only those, and never `pip install`.

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
        4. Output `a.person_id AS distinct_id` as the FIRST column, always. Then list the feature
           columns after it, ordered by how predictive/important you expect them to be (strongest
           signal first). These files are read by non-technical users — a consistent
           `distinct_id, <most-important feature>, …, <least-important feature>` left-to-right order
           makes the model legible at a glance. Give every feature a clear snake_case name.
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

        ### Step 3 — Materialize features, then fit and evaluate (in your sandbox)

        **Your sandbox is already equipped — do NOT `pip install` anything.** numpy, pandas,
        scikit-learn, and pyarrow are pre-installed (the same versions the framework uses to run
        your bundle), so just `import` them.

        **Pull training data with `autoresearch-materialize-features`, NOT `execute-sql`.** Call it with
        `pipeline_id = "{pipeline.pk}"`, `id = "{training_run_id}"`, and your `features_sql`. The framework
        runs it server-side against the labeled training population — no 500-row cap, and the rows never
        pass through your context — then writes four parquet files into your sandbox and returns their
        paths: `train_features_path`, `train_labels_path`, `holdout_features_path`, `holdout_labels_path`
        (features = `distinct_id` + your numeric columns; labels = `distinct_id` + `__label`). The
        train/holdout split and the labels are produced for you — your `features_sql` must NOT add its own
        label or fold columns.

        The feature matrix only changes when `features_sql` changes, so call materialize ONCE per
        `features_sql` and run many model iterations in Python on the same parquet; re-call it only after
        you edit `features_sql`. `execute-sql` is for lightweight schema exploration only — never for
        pulling feature rows (it caps at 500 rows and would force the data through your context).

        **Python fit + eval pattern** (reads the parquet the tool wrote — no data in your context):

        ```python
        import pandas as pd
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score

        # res = the autoresearch-materialize-features response
        train = pd.read_parquet(res["train_features_path"]).merge(
            pd.read_parquet(res["train_labels_path"]), on="distinct_id")
        holdout = pd.read_parquet(res["holdout_features_path"]).merge(
            pd.read_parquet(res["holdout_labels_path"]), on="distinct_id")
        feature_cols = [c for c in train.columns if c not in ("distinct_id", "__label")]
        Xtr, ytr = train[feature_cols].fillna(0).astype(float), train["__label"].astype(int)
        Xho, yho = holdout[feature_cols].fillna(0).astype(float), holdout["__label"].astype(int)
        if yho.nunique() < 2 or ytr.sum() < 5:
            holdout_auc = None  # not enough signal — skip
        else:
            model = LogisticRegression(C=1.0, max_iter=200, random_state=42)
            model.fit(Xtr, ytr)
            holdout_auc = float(roc_auc_score(yho, model.predict_proba(Xho)[:, 1]))
        ```

        **Record each iteration the instant you have its AUC — one call per hypothesis, live.**
        The moment you compute a hypothesis's holdout AUC in Python, and BEFORE you start the next
        hypothesis, call `autoresearch-training-runs-iterations-create` with
        `pipeline_id = "{pipeline.pk}"`, `id = "{training_run_id}"`, the iteration_number,
        recipe_snapshot (`{{"feature_sql": "..."}}`), model_spec (`{{"model_class": "...", "model_params": {{...}}}}`),
        holdout_score (the AUC you computed), status (`"kept"` if it beats your best AUC so far, else
        `"discarded"`), and a one-line agent_description. Do NOT batch these up to record at the end —
        the user watches the iteration trail stream in live as you work, so each must land as it happens.
        Judge `status` against your best-so-far at the time you record; if a later iteration wins, that
        is simply reflected by the climbing scores, not by rewriting earlier ones. These also drive
        champion selection at completion.

        ### Step 4 — Iterate

        Try at least {min_iters} distinct hypotheses — vary which events you count, recency vs
        frequency, cross-event ratios/diversity, property-conditioned counts. After each one, record
        it immediately (above) before moving on — never run several hypotheses and only then record
        them together. Pick the highest holdout AUC as your winner.

        ## Author and upload the winning bundle

        Write the four files so they run STANDALONE in the sandbox under these exact CLI
        contracts, then upload each with `autoresearch-training-runs-artifacts-upload-create`
        (`pipeline_id = "{pipeline.pk}"`, `id = "{training_run_id}"`, `path`, `content_base64`).

        **Comment for a non-technical reader.** These files are saved and shown back to users
        who may not read code. Write them so a curious product manager can follow along:
        - A short module docstring at the top of each .py saying, in plain language, what the
          file does and how it fits the pipeline (e.g. "Trains the model that predicts who will
          download a file in the next 30 days").
        - A one-line comment above each non-obvious step explaining WHY in business terms, not
          what the syntax does (e.g. "# count recent sessions — active users convert more often").
        - In features.sql, comment each feature with the intuition behind it.
        Keep comments concise; explain reasoning, not Python mechanics. Do not let comments
        change the I/O contract or print to stdout.

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

        ## Finalize

        When all three bundle files are uploaded for the winning iteration:

        1. (Optional) confirm with `autoresearch-training-runs-artifacts-retrieve` that
           features.sql, train.py, and predict.py are all present.
        2. **Write `report.md`** — a portable one-page model report for a human reader (think:
           the write-up an ML engineer hands their manager). Upload it with
           `autoresearch-training-runs-artifacts-upload-create` at path `report.md`, exactly like
           the bundle files. It travels with the run and is shared across surfaces, so keep it
           self-contained Markdown — no external links or images. Cover, in this order:
           - **TL;DR** — 1–2 sentences: what this predicts and whether it can be trusted yet.
           - **What it predicts** — target event, horizon, and population in plain words.
           - **How well it works** — holdout AUC, calibration (ECE), and lift@10/@20 explained in
             plain English ("the top 10% of scored users are 3× likelier to convert"). Be honest
             about limits — holdout is checked against realized outcomes later, so do not oversell.
           - **What drives it** — the top features, their direction, and the *intuition* behind
             each, not just a number. Ground this in the importances `train.py` computed (write them
             to its `output.json`), not from memory.
           - **How it was built** — the winning approach and the notable dead-ends, briefly.
           - **Caveats & recommended use** — when to rely on it and when not to.

           Charts: use ```mermaid``` code fences — they render inline and stay portable. Colors are
           themed to PostHog automatically, so do NOT set colors or add `%%{{init}}%%` directives
           (they are stripped in strict render mode); your only job is to supply real data.
           **Never emit an empty chart fence** — every chart MUST contain actual values (with a
           title and axis labels), or omit it entirely. An empty `xychart-beta`/`flowchart` renders
           as a broken error box, which is worse than no chart. Include at minimum a `xychart-beta`
           **bar** chart of the top feature importances and a `xychart-beta` **line** chart of
           holdout AUC across your iterations, populated like this (real numbers from your run):

           ```mermaid
           xychart-beta
               title "Holdout AUC by iteration"
               x-axis [iter0, iter1, iter2]
               y-axis "AUC" 0.5 --> 1.0
               line [0.992, 0.96, 0.992]
           ```

           Add a calibration line (predicted vs realized rate) if it aids the story. Where a chart
           would be overkill (or mermaid can't express it), fall back to compact ASCII/unicode bar
           charts inline — they render in any Markdown surface. Use plain GFM tables for the metrics
           block. If a user suggestion asks for a particular audience or emphasis, honor it.
        3. Call `autoresearch-training-runs-complete-create` with `pipeline_id = "{pipeline.pk}"`
           and `id = "{training_run_id}"`. The backend picks the best iteration, decides
           champion vs challenger, and attaches your uploaded bundle as the model's artifact.
           Also pass two short fields that become this run's learning memory for the NEXT run:
           - `distillation`: 1–2 sentences on what this run learned — the winning signal, the
             key transform, the dead-ends. This is the cheapest thing the next run reads.
           - `recommended_next`: concretely what a future run should try next given what you found.
           The backend derives the rest of the summary (the kept ladder and dead-ends) from your
           recorded iterations, so keep these two fields to judgment only — do not restate the ladder.

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
            "first iteration, decide for each, and RECORD your decision so the human sees it (the",
            "suggestion stays 'queued' in the UI until you do):",
            "- **Translate to an iteration** — spawn one or more iterations. When you record such an",
            "  iteration with `autoresearch-training-runs-iterations-create`, pass `parent_suggestion`",
            "  = the suggestion's ID. That links the iteration to the suggestion and marks it 'acted_on'.",
            "- **Apply as a constraint** — use as context across iterations without a dedicated iteration.",
            "  Call `autoresearch-suggestions-respond` with status='picked_up'.",
            "- **Reject** — violates a guardrail or is irrelevant. Call `autoresearch-suggestions-respond`",
            "  with status='dismissed' and a rationale.",
            "",
            "For EVERY suggestion, call `autoresearch-suggestions-respond` (id, status, agent_response)",
            "to write a one-line note on how you interpreted it — this is the human's only feedback that",
            "their steer was heard. Also cite it in the relevant iteration's agent_description.",
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
    from products.tasks.backend.facade.sandbox import SandboxTemplate
    from products.tasks.backend.models import Task, TaskRun

    now = django_timezone.now()
    training_run = AutoresearchTrainingRun.objects.create(
        pipeline=pipeline,
        status=AutoresearchTrainingRun.Status.RUNNING,
        iteration_budget=iteration_budget,
        started_at=now,
    )

    # Surface the inaugural training run in the pipeline badge. A DRAFT pipeline has no
    # promoted champion yet, so flip it to BOOTSTRAPPING while the first agent run is in
    # flight — otherwise the badge reads "Draft" the whole time the agent is working.
    # Promotion flips BOOTSTRAPPING -> RUNNING; a failed run reverts it to DRAFT.
    if pipeline.status == AutoresearchPipeline.Status.DRAFT:
        pipeline.status = AutoresearchPipeline.Status.BOOTSTRAPPING
        pipeline.save(update_fields=["status", "updated_at"])

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
            # The autoresearch image is the agent-capable base plus pandas/numpy/
            # scikit-learn/pyarrow at system site. The base image lacks the ML libs; the
            # notebook image has the libs but cannot host the agent server — only this
            # image has both, which the agent's training loop needs.
            sandbox_template=SandboxTemplate.AUTORESEARCH_BASE.value,
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
        # The bootstrap never got off the ground — drop back to DRAFT so the pipeline
        # doesn't sit in BOOTSTRAPPING forever with no run behind it.
        if pipeline.status == AutoresearchPipeline.Status.BOOTSTRAPPING:
            pipeline.status = AutoresearchPipeline.Status.DRAFT
            pipeline.save(update_fields=["status", "updated_at"])
        logger.exception("autoresearch_training_launch_failed", pipeline_id=str(pipeline.pk))
        raise
