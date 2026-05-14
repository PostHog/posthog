# `automl` CLI surface

This reference is informational. If the CLI's `--help` disagrees with what's
here, **trust the CLI** — it's the source of truth and may have advanced past
this doc. The CLI lives at `/tmp/workspace/repos/posthog/automl-cli/` in the
sandbox (bind-mounted from the host), so you can also read its source.

## Commands

```text
automl [--log-level debug|info|warning|error] <command> [args]
```

### `prepare-from-hogql`

Run a HogQL query against PostHog and write a parquet snapshot.

```bash
automl prepare-from-hogql \
  --host "$POSTHOG_API_URL" \
  --project-id "$POSTHOG_PROJECT_ID" \
  --api-key "$POSTHOG_PERSONAL_API_KEY" \
  --query-file ./training_query.sql \
  --output ./training_snapshot.parquet \
  [--allow-truncated]
```

- `--query-file` reads the HogQL from disk so you don't have to wrestle shell
  quoting on multi-line queries. There's also `--query` for inline single-line
  queries.
- `--allow-truncated` tells the CLI not to fail if the HogQL API reports the
  result was truncated. PostHog's `/query/` endpoint has row-limit semantics;
  you usually want this flag on for bootstrap snapshots.

**Stdout (success):** single-line JSON

```json
{
  "output_path": "./training_snapshot.parquet",
  "rows": 217,
  "columns": ["person_id", "uploads_14d", "downloads_14d", "target"],
  "project_id": 1,
  "host": "http://host.docker.internal:8000"
}
```

**Stderr:** structured `structlog` lines (one per event). On a 4xx from the
HogQL API, the response body is in the `body` field of an `hogql_request_failed`
event — read it; the body is JSON with `type`, `code`, `detail`.

**Exit codes:**

- `0` — parquet written, JSON on stdout
- `1` — HogQL request failed, validation error, or write failed (read stderr)
- `2` — argparse/click usage error (you passed a bad flag)

### `train`

Train an AutoGluon ensemble against a parquet snapshot.

```bash
automl train \
  --train-parquet ./training_snapshot.parquet \
  --target "<column_name>" \
  --predictions-output ./predictions.parquet \
  --time-limit-s 300 \
  --presets medium_quality \
  --model-archive-output ./model.tar.gz
```

- `--target` is the **column name in the parquet** that holds the label
  (e.g., `target`, `upgraded_in_14d`). It is **not** the PostHog event name —
  see `config.target` vs `config.target_event` in [common pitfalls](./common-pitfalls.md).
- `--presets`: AutoGluon presets. `medium_quality` is the default for bootstrap
  (good signal, fast). `high_quality` and `best_quality` exist but blow the
  300s budget.
- `--time-limit-s` caps the total training time. AutoGluon will stop early if
  it converges, but won't go past this floor.
- `--model-archive-output` writes a `.tar.gz` of the predictor directory so you
  can persist a single file via `upload-model` later.

**Stdout (success):** single-line JSON with `model_path`, `metrics` (dict),
`leaderboard` (list of dicts), `problem_type`, `eval_metric`,
`predictions_path`, `splits_paths`.

**Common training failures:**

- `target column has only one unique value` → your label is constant. Check
  the SQL — the population probably hasn't been filtered to eligible
  positives + negatives.
- `target column has too many missing values` → the LEFT JOIN producing the
  label isn't grouping correctly. Often a `IS NULL` -> 0 mapping is missing.
- AutoGluon presets fall back to subset of models if the dataset is too small;
  this is informational, not a failure.

### `predict`

Run inference on a snapshot using a saved model. **Bootstrap does not call
this** — inference is the inference workflow's job. Mentioned here only for
completeness.

### `upload-model`

Pack a predictor directory as a tar.gz and push it to a destination URI. Used
in retraining flows, not bootstrap. Skip.

### `generate-fixture`

Write a synthetic per-user parquet for end-to-end testing. Not used in
production bootstrap.

## Global options

- `--log-level` sets the structlog level for the CLI. `debug` will print every
  step of the HogQL request, parquet write, AutoGluon iteration. Useful when
  you're iterating on a failure — turn it on briefly, read the events, then
  turn it back to `info`.

## Source location

Everything above is generated from
`/tmp/workspace/repos/posthog/automl-cli/backend/cli.py`. When in doubt:

```bash
cat /tmp/workspace/repos/posthog/automl-cli/backend/cli.py | head -100
```
