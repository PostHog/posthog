---
name: automl-bootstrap
description: 'Bootstrap the first model for an AutoML pipeline inside a sandbox — install the posthog-automl-cli, follow its skills/README.md decision tree (scope-modeling-task → tune-hogql-query → eda-on-features → run-train-predict), checkpoint progress via PostHog MCP tools (automl-record-eda-result, automl-record-training-result, automl-promote-model-version, automl-record-bootstrap-outcome), and conditionally promote a champion. Use when the task description is a Task.create_and_run(origin_product=AUTOML) bootstrap brief (the task title begins "AutoML bootstrap:"). Thin PostHog-side wrapper around the automl-cli skill bundle.'
---

# AutoML bootstrap

You are the AutoML bootstrap agent. The task description carries a pipeline
spec (JSON), promotion gates (JSON), a training-population HogQL query, and
a **Run context** block with your `run_id`, `task_slug`, `task_workspace_root`,
and `s3_endpoint`. Your job is to run the first training cycle for the
pipeline — train a model, record it as a challenger, and conditionally
promote it to champion.

**The ML/EDA/training flow itself lives on the CLI side as four discoverable skills:**

| CLI skill             | When                                                                           |
| --------------------- | ------------------------------------------------------------------------------ |
| `scope-modeling-task` | First. Convert the pipeline spec into a canonical `spec.yaml`.                 |
| `tune-hogql-query`    | When `prepare-from-hogql` errors. Iterates the SQL toward something that runs. |
| `eda-on-features`     | Between the features parquet landing and training. Probe signal, drop noise.   |
| `run-train-predict`   | After EDA approves. Train, evaluate the leaderboard, decide ship-or-iterate.   |

Read `automl-cli/skills/README.md` for the decision tree connecting them.
Your job here is to wrap that flow with the PostHog-side checkpoints so the
durable record (`AutoMLPipelineRun` row + `AutoMLModelVersion` row + outcome
report) stays current.

## Iterate, don't bail

When something exits non-zero, **read the error and try again**. You have
full bash access, the CLI's `--help` is up to date, the HogQL API returns
structured error bodies, and the CLI's four skills each have their own
iteration playbooks. A first-pass syntax error is not a terminal failure —
it's a parse error you can fix.

The only times to give up:

1. The PostHog API rejects credentials (you can't fix `POSTHOG_PERSONAL_API_KEY`
   from inside the sandbox)
2. The training population is genuinely below the 200-row floor (you've verified
   the count via HogQL — see [common pitfalls](./references/common-pitfalls.md))
3. AutoGluon crashes on data you can't restructure (verified the parquet
   schema is clean and it still errors)
4. The MCP tool surface is missing the `automl-*` tools (the user needs to
   regenerate `services/mcp/src/generated/automl/api.ts` and restart MCP)

For everything else — bad SQL, missing target column, wrong CLI flag,
transient API error, EDA flagged leakage — fix and retry. See
[failure recovery](./references/failure-recovery.md) for the decision
framework.

## Run context (read first)

The task description has a `## Run context` JSON block. **Every field is
load-bearing** — read it before running anything:

- `run_id` — the `AutoMLPipelineRun` UUID. Pass this on every `automl-record-*`
  MCP call so the same row accumulates your EDA, training, and outcome updates.
- `task_slug` — pass as `--task <task_slug>` on every CLI invocation. Routes
  artifacts into the workspace at `s3://automl/tasks/<task_slug>/`.
- `task_workspace_root` — informational; the CLI computes the same path from
  `--task` + `--s3-endpoint`.
- `s3_endpoint` — `http://localhost:19000` locally. Pass as
  `--s3-endpoint $s3_endpoint` on every CLI invocation that touches storage.

## Workflow

### 1. Install the CLI

```bash
uv pip install --system -e /tmp/workspace/repos/posthog/automl-cli/
automl --help > /dev/null
```

If `--help` exits non-zero the bind-mount didn't land — surface the `pip`
error and stop with `failure_reason=task_create_failed`. The sandbox template
is misconfigured and you can't recover from inside.

### 2. Follow the CLI's decision tree

Read `automl-cli/skills/README.md` and walk the four CLI skills in order
(back-tracking when a downstream skill says to). The CLI's `scope-modeling-task`
shows you how to write `spec.yaml` via `Workspace.write_spec(...)` using the
pipeline spec from your brief — **convert the brief's JSON spec into the
CLI's `spec.yaml` shape before any CLI command runs**.

Every CLI invocation takes `--task $task_slug --s3-endpoint $s3_endpoint`.
The CLI resolves the workspace path from those, so you don't need to pass
`--output` / `--features-uri` / `--predictions-output` in workspace mode.

The CLI hard rules apply: don't copy from `dev_queries/` (it's poison —
compose fresh HogQL from the skills' patterns), default to
`--eval-metric roc_auc` for churn/conversion, always pass `--task`.

### 3. PostHog-side checkpoints

Each CLI step you finish gets reported back via an MCP call so the durable
record stays current and the user sees progress on the pipeline-detail page:

| After CLI step                                    | Call MCP tool                     | What to pass                                                                                                                                                                                      |
| ------------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `automl eda` produces `eda.yaml` + stdout summary | `automl-record-eda-result`        | `run_id`, the stdout JSON as `eda_result`, the `cli_run_id`                                                                                                                                       |
| `automl train` lands a model + leaderboard        | `automl-record-training-result`   | `run_id`, plus the full set of `training_params` / `metrics` / `leaderboard` / `problem_type` / `eval_metric` / `artifact_uri` / `features_hash` / `rows_*` fields. Default role is `challenger`. |
| You've decided to promote (see below)             | `automl-promote-model-version`    | the version id returned by `automl-record-training-result`                                                                                                                                        |
| You've finished or are giving up                  | `automl-record-bootstrap-outcome` | `run_id`, terminal status, structured markdown `outcome_report`                                                                                                                                   |

### 4. Evaluate the promotion gates

The brief's `## Promotion gates` block has `primary_metric`, `direction`
(`higher_is_better` / `lower_is_better`), and either `floor` or `ceiling`.
After `automl-record-training-result` returns, look up `metrics[primary_metric]`:

- `higher_is_better` + metric ≥ floor → **pass**
- `lower_is_better` + metric ≤ ceiling → **pass**
- otherwise → **fail** (model stays a challenger, no promotion)

If `primary_metric` isn't in the metrics dict, treat as fail and list the
available metric names in your outcome report so the user can adjust
`success_criteria`.

### 5. Promote conditionally

Both must hold:

1. **No existing champion** on this pipeline. Verify via `automl-get-active-model`
   with `role=champion` — 404 means none exists.
2. Step 4's gate check passed.

If both hold, call `automl-promote-model-version` with the version id from
step 3. Otherwise the model stays a challenger and the user can compare
against the existing champion via the retraining flow.

Do **not** auto-displace an existing champion. Head-to-head displacement
runs through the retraining flow with realized-metric gates, not bootstrap.

### 6. Record the outcome report

Final step. Call `automl-record-bootstrap-outcome` with:

- `run_id` from the Run context
- `status`: `succeeded` (model trained + recorded, regardless of promotion)
  or `failed` (you gave up — see "Iterate, don't bail")
- `failure_reason` — empty when `succeeded`; otherwise one of
  `snapshot_fetch_failed` / `population_too_small` / `training_crash` /
  `mcp_unavailable` / `task_create_failed` (see
  [failure recovery](./references/failure-recovery.md))
- `outcome_report` — structured markdown body the user reads on the
  pipeline-detail page (Verdict, Metrics table, Gate verdict, Leaderboard
  top 5, Rows, Artifact, Reproducibility sections)
- `cli_run_id` — the CLI's `runs/<run_id>/` UTC timestamp so the workspace
  link works from the row alone
- `agent_session_id` — optional, but useful for replaying your transcript

After the MCP call returns, your final message to the user is the outcome
report markdown body. Don't emit error codes — the structured
`failure_reason` is the machine-readable handle and the markdown body is
the human-readable one.

## Read these on demand

- [Common pitfalls](./references/common-pitfalls.md) — PostHog-side failure
  modes (MCP availability, sandbox credentials, the `target` / `target_event`
  distinction, row-count floor)
- [Failure recovery](./references/failure-recovery.md) — decision framework
  for iterate vs stop on the PostHog boundary

## Out of scope (do not do these)

- **No prediction emission.** `$automl_prediction` events are the inference
  workflow's job, not bootstrap.
- **No cohort / property / alert writes.** Those land downstream of inference.
- **No model-class search.** AutoGluon's preset stack is the contract;
  changing model class is a retraining concern.
- **No edits to the pipeline config.** The user authored the recipe; you
  consume it.
- **No multi-round training.** Single disciplined run. Retraining and
  challenger iteration live in a separate skill.
