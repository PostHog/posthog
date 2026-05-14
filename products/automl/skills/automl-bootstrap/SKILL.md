---
name: automl-bootstrap
description: 'Bootstrap the first model for an AutoML pipeline inside a sandbox — install the posthog-automl-cli, fetch the training snapshot via HogQL, train via AutoGluon, record the result as a challenger model version, evaluate gates, and conditionally promote to champion. Use when the task description is a `Task.create_and_run(origin_product=AUTOML)` bootstrap brief (the task title begins "AutoML bootstrap:"). Covers the workflow steps, the `automl` CLI surface, common failure modes the agent should iterate on rather than bail from, and the promotion-gate decision rules.'
---

# AutoML bootstrap

You are the AutoML bootstrap agent. The task description carries a pipeline spec
(JSON), promotion gates (JSON), and a training-population HogQL query. Your job
is to **train the first model** for that pipeline, persist the run as an
`AutoMLModelVersion`, and — if it clears the gates — promote it to champion.

This is a single disciplined training run with the freedom to iterate on
recoverable failures. Retraining and model search run against a different
workflow — don't do those here.

## Read these on demand

- [CLI surface](./references/cli-surface.md) — `automl` subcommands, args, return shapes
- [Common pitfalls](./references/common-pitfalls.md) — known failure modes and how to fix them (HogQL precedence, target columns, leakage, etc.)
- [Failure recovery](./references/failure-recovery.md) — when to iterate, when to give up

## Iterate, don't bail

When the CLI exits non-zero, **debug the inputs and retry**. You have full bash
access, the CLI's `--help` is up to date, and the HogQL `query/` endpoint
returns structured error bodies you can read. A first-pass syntax error in the
training query is not a terminal failure — it's a parse error you can fix.

The only times to give up:

1. The PostHog API rejects credentials (your `POSTHOG_PERSONAL_API_KEY` is wrong; you can't fix this from inside the sandbox)
2. The training population genuinely has too few rows (you've verified the count via HogQL, and it's below the 200-row floor — see step 2 for the hackathon-grade threshold; production will raise this once we have realistic data volume)
3. AutoGluon training itself crashes on data you can't fix (e.g., the target column is structurally absent and the SQL can't be adjusted to produce it)

For everything else — bad SQL, missing column, wrong CLI argument, transient
API error — fix and retry.

## What you have available

- **Bash** in the sandbox; full read/write under `/tmp/workspace`.
- **`automl` CLI** on `PATH` after step 1 (`uv pip install --system -e ...`). Read its `--help` if anything in this skill seems wrong — the CLI is the source of truth.
- **PostHog MCP tools** scoped to `automl:read` + `automl:write`. The ones you'll need:
  - `automl-record-training-result` — write the trained model as a challenger
  - `automl-get-active-model` — check for an existing champion
  - `automl-promote-model-version` — promote the challenger
- **Env vars set by sandbox provisioning** (do not override):
  - `POSTHOG_API_URL` (local dev: `http://host.docker.internal:8000`; cloud: `https://us.posthog.com`)
  - `POSTHOG_PROJECT_ID` (numeric team id)
  - `POSTHOG_PERSONAL_API_KEY` (OAuth-issued, scoped to the user who started this bootstrap)

## Workflow

### 1. Verify the CLI is installed

The sandbox provisioning installs `posthog-automl-cli` editable from a
bind-mounted source at `/tmp/workspace/repos/posthog/automl-cli/`. Confirm it's
on `PATH`:

```bash
automl --help > /dev/null
```

If this exits non-zero, the bind-mount or install didn't land — the sandbox
template is misconfigured and you can't recover from inside. Surface the
actual `pip` error and stop.

### 2. Fetch the training snapshot

Write the pipeline's training-population HogQL to a file (so multi-line quoting
doesn't fight you), then run `prepare-from-hogql`:

```bash
cat > ./training_query.sql <<'HOGQL'
<paste the training query from the task description>
HOGQL

automl prepare-from-hogql \
  --host "$POSTHOG_API_URL" \
  --project-id "$POSTHOG_PROJECT_ID" \
  --api-key "$POSTHOG_PERSONAL_API_KEY" \
  --query-file ./training_query.sql \
  --output ./training_snapshot.parquet \
  --allow-truncated
```

Stdout is a single-line JSON with `output_path`, `rows`, `columns`, `project_id`,
`host`. Parse it.

**If the CLI exits non-zero, read the error and iterate.** Common cases handled
in [common pitfalls](./references/common-pitfalls.md) — read it before giving
up. Especially: operator precedence on `AND ... BETWEEN ...`, missing target
column, and the difference between `config.target` (snapshot column name) and
`config.target_event` (PostHog event name).

Then check the result:

- `rows` is zero or missing → the SQL produced no rows. Either the population
  is genuinely empty (give up with a clear message) or your filter is wrong
  (fix and retry).
- `columns` does not include `config.target` (for classification/regression) →
  the SELECT clause needs the `target` column. Adjust the SQL and retry.
- `rows < 200` → below the trainer's useful-model floor. **This is the
  hackathon-grade threshold** — generalization on a binary classifier with
  <200 rows is unreliable, and AutoGluon's stratified split + cross-validation
  routines start to misbehave below that. Stop with a clear message; the user
  needs more data before this pipeline is trainable. (Production will raise
  this floor once we have realistic volumes; for now, 200 lets the local-dev
  Hedgebox run complete end-to-end against the synthetic ~217-signer cohort.)

Record the exact HogQL you ran in a scratch note — it goes into the outcome
report's reproducibility section.

### 3. Train

```bash
automl train \
  --train-parquet ./training_snapshot.parquet \
  --target "<config.target>" \
  --predictions-output ./predictions.parquet \
  --time-limit-s 300 \
  --presets medium_quality \
  --model-archive-output ./model.tar.gz
```

Stdout JSON: `model_path`, `metrics`, `leaderboard`, `problem_type`,
`eval_metric`, `predictions_path`, `splits_paths`. Parse it.

Do **not** re-implement training inside the sandbox — the CLI wraps AutoGluon's
preset stack. If training itself crashes, check the data first (is the target
column constant? all-null? mismatched dtype?); if the data is fine and
AutoGluon is the one crashing, that's a CLI bug, not a brief bug — stop with
the stderr tail.

### 4. Record as challenger

Call the MCP tool `automl-record-training-result` with `role: "challenger"`.
**Always** record as challenger first — promotion is the explicit next step.

Required body fields (from step 3's JSON):

- `metrics`, `leaderboard`, `eval_metric`, `problem_type`, `artifact_uri` (use
  `model_path`)
- `training_params`: `{"target": "<config.target>", "presets": "medium_quality", "time_limit_s": 300, "training_query": "<the HogQL you ran in step 2>"}`
- `features_hash`: 16-hex sha256 of `json.dumps(sorted(columns_from_step_2), sort_keys=True).encode()`
- `rows_train` / `rows_val` / `rows_test`: from step 3 JSON if present, else `null`

The tool returns the persisted `AutoMLModelVersion` JSON. Stash its `id` — that's
what predictions will carry as `$automl_prediction.$model_version_id`.

### 5. Evaluate the gates

The task description embeds `primary_metric`, `direction`, and either `floor`
(higher-is-better) or `ceiling` (lower-is-better). Look up `metrics[primary_metric]`.

- `direction == "higher_is_better"` and `metric >= floor` → **pass**
- `direction == "lower_is_better"` and `metric <= ceiling` → **pass**
- Anything else → **fail** (the model stays a challenger, no promotion)

If `primary_metric` isn't in `metrics`, treat as fail and list the available
metric names in your outcome report so the user can adjust `success_criteria`.

### 6. Promote (conditional)

Both must hold:

1. **No existing champion** on this pipeline. Verify via
   `automl-get-active-model` with `role=champion` — a 404 means none exists.
2. Step 5's gate check passed.

If both hold, call `automl-promote-model-version` with the version id you
stashed in step 4.

Do **not** auto-displace an existing champion. Head-to-head displacement is
the retraining flow's job, not bootstrap. Record the existing champion's id in
the outcome report so the user can compare.

### 7. Outcome report

Final output of the run. Structured markdown the user reads on the pipeline
detail page. Include:

- **Verdict**: `promoted_to_champion` / `recorded_as_challenger` / `failed`
- **Model version id** (uuid) — what propagates onto `$automl_prediction` events
- **Metrics**: full `metrics` table from step 3
- **Gate verdict**: which gate, what the value was, why it passed or failed
- **Leaderboard**: top 5 rows from step 3's `leaderboard`
- **Rows**: train / val / test split sizes
- **Artifact**: the model directory path
- **Reproducibility**: the HogQL you ran (final version), the features hash, the training params

## Out of scope (do not do these)

- **No prediction emission.** `$automl_prediction` events are the inference workflow's job.
- **No cohort / property / alert side effects.** Those land downstream of inference, not training.
- **No model-class search.** The trainer uses AutoGluon's preset stack; changing model class is a retraining concern.
- **No edits to the pipeline config.** The user authored the recipe; you consume it.
- **No multi-round training.** Single disciplined run. If you genuinely cannot get a training run to succeed after iterating on the inputs, surface what you tried and stop.

## When you're done

Write the outcome report as your final message. Don't emit specific error
codes — the workflow has full visibility into your bash invocations and MCP
calls, and the structured outcome report is what the user reads.
