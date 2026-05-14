---
name: automl-inference
description: 'Score an active pipeline''s population once via the champion model — install the automl-cli, run a single ``automl refresh-task`` invocation that fetches a fresh inference snapshot + scores it + writes predictions parquet to S3, then call ``automl-record-inference-outcome`` once with the parsed manifest. Use when the task description begins "AutoML inference:" (Task.create_and_run with origin_product=AUTOML, run_kind=INFERENCE). Thin PostHog-side wrapper around ``automl-cli refresh-task``. Mirrors the automl-bootstrap shape but does NO training and produces NO new model — the champion at MODEL_HEAD is what scores the population.'
---

# AutoML inference

You are the AutoML inference agent. The task description carries a pipeline
spec (JSON), a **Run context** block (with `run_id`, `task_slug`,
`task_workspace_root`, `s3_endpoint`, AWS creds, `parent_run_id`, and
optional `champion_model_run_id` / `champion_model_version_id`), and the
inference-population HogQL. Your job is **single-shot**: one CLI call, one
MCP checkpoint, no training, no displacement.

**The ML/data-fetch flow lives on the CLI side.** The CLI's
`automl refresh-task` does everything in one shot:

1. Reads the workspace's `MODEL_HEAD` to find the champion model
2. Fetches a fresh inference snapshot via the supplied HogQL
3. Loads the model, scores the snapshot
4. Writes `predictions.parquet` + a manifest under
   `<task_workspace_root>/predictions/<inference_run_id>.*`
5. Emits the manifest as JSON on stdout

Your PostHog-side contract: parse that JSON, pass it through to
`automl-record-inference-outcome`. **Do not invoke `automl train`,
`automl eda`, or any other CLI subcommand** — inference doesn't iterate
on the model.

See [`automl-cli/skills/schedule-refresh.md`](../../../../../automl-cli/skills/schedule-refresh.md)
for the contract `refresh-task` exposes (exit code, stdout shape, env vars,
abort verdicts).

## Iterate, don't bail (sparingly)

Inference is much narrower than bootstrap or retrain — there's only one CLI
invocation that can fail. The four times to give up:

1. **PostHog credentials rejected** — you can't fix
   `POSTHOG_PERSONAL_API_KEY` from inside the sandbox. Surface with
   `failure_reason=mcp_unavailable` (treat any auth-side outage the same).
2. **The MCP tool surface is missing `automl-*` tools** — same recovery as
   bootstrap. Surface with `failure_reason=mcp_unavailable` so the operator
   regenerates `api.ts` on the host.
3. **The pipeline has no champion** — `refresh-task` exits with a usage
   error pointing at missing `MODEL_HEAD`. Should be impossible because the
   facade refuses to dispatch without a winning run, but if it happens,
   surface with `failure_reason=no_champion`.
4. **`refresh-task`'s pre-flight `--estimate` aborts** — too few rows or a
   `likely_504` verdict. Try once with `--skip-estimate` only if the
   pipeline's HogQL uses a non-standard shape that the probe can't parse;
   otherwise surface with `failure_reason=snapshot_fetch_failed` and the
   estimate verdict in the outcome report.

For everything else — transient HogQL timeouts, S3 hiccups, model-load
glitches — retry the single `refresh-task` call up to **2 times** with a
short backoff. If still failing, surface the verbatim error and exit.

Don't try to repair the model from this run. **Inference doesn't iterate.**

## Workflow

### 1. Install the CLI

```bash
uv pip install --system -e /tmp/workspace/repos/posthog/automl-cli/
automl --help > /dev/null
```

Same as bootstrap and retrain. If install fails, surface and stop with
`failure_reason=task_create_failed`.

### 2. Export S3 credentials

The CLI's `pyarrow` / `boto3` clients pick these up:

```bash
export AWS_ACCESS_KEY_ID=$aws_access_key_id
export AWS_SECRET_ACCESS_KEY=$aws_secret_access_key
export AWS_DEFAULT_REGION=$aws_default_region
```

(Values from the Run context block. Missing keys → CLI calls fail with
`Bucket not found` or `403`.)

### 3. Run `automl refresh-task`

Single invocation. Pass the inference HogQL inline via `--query` (or write
it to a file and pass `--query-file`) so the CLI substitutes it for the
workspace's HEAD query (which is the _training_ query, not what we want
for inference).

```bash
automl refresh-task \
  --task "$task_slug" \
  --project-id "$project_id" \
  --host "http://host.docker.internal:8000" \
  --s3-endpoint "$s3_endpoint" \
  --query "$inference_hogql" \
  --sample-shard 9 \
  --skip-estimate
```

Notes:

- `--sample-shard 9` puts the inference cohort on a disjoint hash slot from
  the training shard 0 — see `automl-cli/skills/tune-hogql-query.md`.
- `--skip-estimate` is fine for hackathon volumes (a few hundred rows
  on the local Hedgebox dataset). For large prod populations, drop the flag
  and let the probe protect against `likely_504`.
- Capture stdout — it's a single JSON object with the manifest.
- Non-zero exit → see "Iterate, don't bail" above for the failure tag.

### 4. Record the outcome

Single MCP call, with the parsed JSON manifest stamped into
`inference_result`:

```text
mcp__posthog__exec call automl-record-inference-outcome {
  "id": "<pipeline_id>",
  "run_id": "<run_id>",
  "status": "succeeded",
  "outcome_report": "## Inference complete\n\nScored <N> rows ...",
  "inference_result": <verbatim manifest JSON from refresh-task stdout>
}
```

(`<pipeline_id>` and `<run_id>` come from the Run context block.)

The PostHog-side event-emission step reads `inference_result.predictions_uri`
out of that record to fetch the parquet from S3 and emit one
`$automl_prediction` event per row. **Don't try to emit events from inside
the sandbox** — the agent's job ends at `record-inference-outcome`.

### 5. Outcome report conventions

A short markdown body — the user reads it on the pipeline-detail page.
Mention:

- **Verdict** (one line: scored / failed / aborted)
- **Rows scored** (from `predictions_count`)
- **Predictions URI** (from `predictions_uri`)
- **Model run id** (from `model_run_id` — the champion's CLI run id)
- **Inference run id** (from `inference_run_id` — the CLI's UTC timestamp)
- **Caveats** if any (e.g. used `--skip-estimate`, sample-shard collision risk)

Keep it under 30 lines. The full manifest is already in `inference_result`.

## On failure

Same shape as bootstrap / retrain — one MCP call, terminal status, compact
`failure_reason` tag, verbatim error in the outcome report. Examples:

- `snapshot_fetch_failed` — HogQL timed out or the estimate aborted
- `model_load_failed` — couldn't pull the champion model from S3
- `predict_crashed` — AutoGluon raised during scoring
- `mcp_unavailable` — record call itself blew up (hard to recover from
  inside the sandbox; the surrounding workflow will mark the run aborted)
- `task_create_failed` — CLI install failed

The pipeline status stays ACTIVE either way. The next scheduled inference
run retries; the existing champion keeps serving.
