---
name: automl-retrain
description: 'Iterate on an AutoML pipeline''s champion — load the previous winning recipe via parent_run_id from the brief''s Run context, vary one knob (AutoGluon preset OR feature recipe edits OR sample size — never multiple at once) based on what the parent run missed, train a challenger via the automl-cli skills/README.md decision tree, evaluate the three-layer displacement gate (offline + realized + autonomy), and conditionally promote. Use when the task description begins "AutoML retrain:" (Task.create_and_run with origin_product=AUTOML, run_kind=RETRAIN). Thin PostHog-side wrapper around the automl-cli skill bundle, mirroring the automl-bootstrap shape with parent-run reasoning bolted on.'
---

# AutoML retrain

You are the AutoML retraining agent. The task description carries a pipeline
spec (JSON), promotion gates (JSON), a **Run context** block (with `run_id`,
`task_slug`, `task_workspace_root`, `s3_endpoint`, AWS creds, **and
`parent_run_id`**), a **Parent run** summary (the previous winning recipe's
metrics + leaderboard + EDA flags), and the training-population HogQL. Your
job is to **iterate** on the parent: train a challenger that's measurably
better, and conditionally displace the existing champion.

**The ML/EDA/training flow itself lives on the CLI side as four discoverable skills:**

| CLI skill             | When                                                                              |
| --------------------- | --------------------------------------------------------------------------------- |
| `scope-modeling-task` | Verify the existing `spec.yaml` is still valid (retraining doesn't rescope).      |
| `tune-hogql-query`    | When `prepare-from-hogql` errors, OR when you're varying the feature set.         |
| `eda-on-features`     | Only re-run if the feature set changed. Otherwise the parent's EDA still applies. |
| `run-train-predict`   | After EDA confirms (or you skipped it).                                           |

Read `automl-cli/skills/README.md` for the decision tree. Your PostHog-side
contract: read the parent, pick _one_ knob, walk the CLI flow (skip steps
that don't change), record back via MCP at each checkpoint.

## The retraining contract — two key differences from bootstrap

1. **Read the parent run first.** The brief's `## Parent run` section has the
   summary inline; pull the full row with `automl-get-run` (via the
   `parent_run_id` from Run context) if you need more than the summary.
2. **Vary one knob per iteration.** Don't change everything at once — the
   iteration log loses meaning if every variable shifts. The skill's decision
   tree below picks the knob for you.

## Iterate, don't bail

Same iteration philosophy as bootstrap. Read errors, adjust inputs, retry.
The four times to give up:

1. PostHog credentials rejected (you can't fix `POSTHOG_PERSONAL_API_KEY`
   from inside the sandbox)
2. The training population dropped below the 200-row floor since the
   parent's run (data deleted? horizon-eligibility filter too tight?)
3. AutoGluon crashes on data that's been structurally fine before
4. The MCP tool surface is missing `automl-*` tools (regenerate api.ts on
   the host)

Boundary failures + their `failure_reason` tags carry over from bootstrap —
see [the bootstrap skill's failure-recovery](../automl-bootstrap/references/failure-recovery.md)
and [common-pitfalls](../automl-bootstrap/references/common-pitfalls.md). Don't duplicate them here.

## Workflow

### 1. Install the CLI

```bash
uv pip install --system -e /tmp/workspace/repos/posthog/automl-cli/
automl --help > /dev/null
```

(Same as bootstrap. If install fails, surface and stop with
`failure_reason=task_create_failed`.)

### 2. Read the parent run

The brief's `## Parent run` block has the summary. Use it to pick the knob.
If you want the _full_ parent record (e.g. raw outcome report, full
leaderboard), pull via:

```text
mcp__posthog__exec call automl-get-run {"id": "<pipeline_id>", "run_id": "<parent_run_id>"}
```

(Both `<pipeline_id>` and `<parent_run_id>` come from the Run context.)

### 3. Pick one knob to vary

Decision tree, in priority order:

| Parent run signal                                                   | Knob to try                                     | What changes                                                    |
| ------------------------------------------------------------------- | ----------------------------------------------- | --------------------------------------------------------------- |
| EDA `suspect_target_leakage` is non-empty                           | Drop those features from the query.             | Training query — recompose, run CLI's `tune-hogql-query` first. |
| EDA `low_signal_features` is large + parent metric below ceiling    | Drop low-signal features, keep only top-K.      | Training query.                                                 |
| Parent leaderboard val ≈ test (no overfit) AND metric below ceiling | Bump preset: `medium_quality` → `good_quality`. | `--preset good_quality` (no query change).                      |
| Parent metric variance high across leaderboard rows                 | Bump sample size via `--sample-pct`.            | `prepare-from-hogql` flags only.                                |
| Parent metric barely cleared floor (≤ floor + 0.02)                 | Bump training budget: triple `--time-limit-s`.  | `--time-limit-s` (no query change).                             |

If none apply (parent was clean and at-ceiling on a high preset), record a
no-op outcome: `automl-record-bootstrap-outcome` with `status=succeeded`,
`outcome_report` explaining nothing to vary, and **don't** train a new
model. Wastes the sandbox budget for negligible gain.

Write your knob choice + rationale into a scratch file early — it goes into
the outcome report's reproducibility section.

### 4. Walk the CLI's decision tree (skip steps that don't change)

`scope-modeling-task` is usually a no-op for retraining (the spec was
already written by the parent). You can skip it.

- **Query changed** (knob = feature edits)? Run `tune-hogql-query` patterns;
  edit the training query; submit via `prepare-from-hogql --task $task_slug`.
- **Query unchanged**? Skip prepare-from-hogql — the parent's features
  parquet is still in the workspace.
- **Feature set changed**? Run `automl eda --task $task_slug` and call
  `automl-record-eda-result` with the new EDA payload.
- **Feature set unchanged**? Skip EDA. The parent's eda_result still applies.
- **Always**: `automl train --task $task_slug` with the new flags.

Every CLI invocation takes `--task $task_slug --s3-endpoint $s3_endpoint`.

### 5. PostHog-side checkpoints

| After CLI step                             | Call MCP tool                     | What to pass                                                                  |
| ------------------------------------------ | --------------------------------- | ----------------------------------------------------------------------------- |
| `automl eda` (only if you re-ran it)       | `automl-record-eda-result`        | `run_id`, eda payload, `cli_run_id`                                           |
| `automl train` lands a model + leaderboard | `automl-record-training-result`   | `run_id` **always**, plus full training fields. Default role is `challenger`. |
| You've decided to promote (see step 6)     | `automl-promote-model-version`    | the version id                                                                |
| You've finished or are giving up           | `automl-record-bootstrap-outcome` | `run_id`, terminal status, structured `outcome_report`                        |

### 6. Evaluate the three-layer displacement gate

This is where retraining differs from bootstrap — you _can_ displace an
existing champion.

**a. Offline gate.** Challenger's primary metric must clear the higher of:

- The pipeline's `success_criteria` floor (from the brief's Promotion gates block)
- The parent run's primary metric (you found a real lift, not just a basement clear)

**b. Realized gate.** If the existing champion has been serving long enough
for prediction horizons to elapse:

- Compute champion's realized metric on the same population. (When the
  validation table lands, this is a single query — for now you may have to
  pull `$automl_prediction` events + ground-truth label events and compute
  it yourself.)
- Challenger's offline metric must beat champion's realized metric by at
  least the realized margin (TBD — for v0 use a 5% relative improvement as
  a placeholder; revisit when the validation table lands).
- If the champion is too new (no horizons elapsed), skip the realized check
  and use offline only.

**c. Autonomy gate.** Look up `pipeline.autonomy`:

- `shadow_only` → **never displace**. Leave challenger as challenger; events
  emit when the inference workflow runs.
- `champion_only` (default) → **never auto-displace**. Leave challenger;
  outcome report flags "ready for review" so the user can promote manually.
- `promote_eligible` → **displace** when (a) + (b) both pass. Call
  `automl-promote-model-version`.

### 7. Record the outcome

`automl-record-bootstrap-outcome` (we use the same MCP tool for now — the
name keeps the bootstrap heritage; a future `automl-record-run-outcome`
rename is on the TODO list).

The outcome report should always include:

- **Verdict**: `displaced_champion` / `recorded_as_challenger_pending_review` /
  `recorded_as_challenger_shadow_only` / `no_op_parent_at_ceiling` / `failed`
- **Knob varied**: which one from step 3's decision tree, with rationale
- **Parent metrics**: from the brief's Parent run block
- **Challenger metrics**: from step 5's `automl-record-training-result`
- **Gate-by-gate verdict**: offline + realized + autonomy
- **Leaderboard top-5**: from training output
- **Iteration depth**: chase `parent_run_id` back to bootstrap to count
  how many iterations deep this run is (`automl-list-runs` makes this easy)

## Out of scope (retrain v0)

- **Multi-knob variation per iteration.** One knob = one signal.
- **Multi-challenger experiments.** One challenger at a time (DB-enforced).
- **Cross-pipeline lift comparison.** Pipelines are isolated.
- **Re-scoping** (changing target, horizon, framing). That's a new pipeline.
- **Inference / `$automl_prediction` event emission.** That's a separate workflow.

## Reference docs

- [Bootstrap common pitfalls](../automl-bootstrap/references/common-pitfalls.md)
- [Bootstrap failure recovery](../automl-bootstrap/references/failure-recovery.md)
- CLI decision tree: `automl-cli/skills/README.md`
