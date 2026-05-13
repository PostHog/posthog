# AutoML hackathon prototype

End-to-end pipeline: **DuckDB → Polars → AutoGluon → MLflow → predictions parquet**, with HogQL feature pulls from any PostHog tenant.

## Layout

```text
products/automl/
├── pyproject.toml          # uv workspace member, ML deps pinned here
├── main.py                 # console entry point → CLI
├── queries/
│   └── churn_features.sql  # leak-free biweekly churn HogQL query
└── backend/
    ├── data/
    │   ├── loader.py         # DuckDB wrapper, parquet I/O (local + s3://) and Postgres
    │   ├── posthog_source.py # HogQL via public API + personal API key (no Django)
    │   └── synthetic.py      # per-user fixture with a binary churn target
    ├── training/
    │   └── trainer.py        # AutoGluon TabularPredictor + MLflow + train/val/test split
    ├── inference/
    │   └── predictor.py      # load model, predict_batch, write parquet
    ├── pipeline.py           # run_end_to_end orchestration
    └── cli.py                # click commands (generate-fixture, run, prepare-from-hogql)
```

## Install

This product is a `uv` workspace member. ML deps live in `products/automl/pyproject.toml` and aren't synced by a bare `uv sync` — use `--package automl` or `--all-packages`:

```bash
uv sync --package automl
```

Pulls in `autogluon.tabular[catboost,fastai,lightgbm,xgboost]`, `mlflow`, `torch`, `polars`, `duckdb`, `pyarrow`, `requests`, `structlog`, `click`. First install is large (~2 GB) and takes a few minutes.

## CLI overview

Top-level option on every command:

| Option        | Default | Notes                                                                              |
| ------------- | ------- | ---------------------------------------------------------------------------------- |
| `--log-level` | `INFO`  | `DEBUG`, `INFO`, `WARNING`, `ERROR`. Logs go to stderr; JSON results go to stdout. |

Subcommands: `generate-fixture`, `prepare-from-hogql`, `run`.

## Quick smoke test on synthetic data

```bash
python -m products.automl.backend.cli generate-fixture /tmp/users.parquet --n-users 500

python -m products.automl.backend.cli run \
  --train-parquet /tmp/users.parquet \
  --target churned \
  --predictions-output /tmp/predictions.parquet \
  --time-limit-s 30
```

The `run` command prints a JSON result with `model_path`, `mlflow_run_id`, `metrics`, `predictions_path`, `predictions_count`. Structured logs (`pipeline_start`, `train_split`, `training_complete`, `pipeline_done`, etc.) go to stderr.

## Pull real features from any PostHog tenant via HogQL

`prepare-from-hogql` calls the public `/api/projects/{project_id}/query/` endpoint — the same path the PostHog MCP server uses. Works against us-cloud, eu-cloud, and self-hosted instances. No Django setup required, just a personal API key.

```bash
# create a personal API key at <host>/me/settings#personal-api-keys
# with the query:read scope, then either export it or pass --api-key
export POSTHOG_PERSONAL_API_KEY=phx_...

python -m products.automl.backend.cli prepare-from-hogql \
  --host https://us.posthog.com \
  --project-id 2 \
  --query-file products/automl/queries/churn_features.sql \
  --sample-pct 1 \
  --output /tmp/team_features.parquet
```

`churn_features.sql` is a leak-free biweekly churn query: features come from a past window ending at `now()-14d`, target comes from the 14-day future window after the cutoff. Restricts to identified-ish users (via HAVING on `$identify`) and recently-active users (within 21 days of the cutoff).

### `prepare-from-hogql` flags

| Flag                       | Default                                 | Notes                                                                                                                                |
| -------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `--project-id`             | (required)                              | The PostHog project ID.                                                                                                              |
| `--host`                   | `https://us.posthog.com`                | EU cloud: `https://eu.posthog.com`. Self-hosted: your URL.                                                                           |
| `--api-key`                | `$POSTHOG_PERSONAL_API_KEY`             | Personal API key with `query:read` scope.                                                                                            |
| `--query` / `--query-file` | (one required)                          | Mutually exclusive.                                                                                                                  |
| `--output`                 | (required)                              | Local path or `s3://` URL for the result parquet.                                                                                    |
| `--sample-pct`             | `10` if query uses `{sample_threshold}` | Float. Computes `{sample_threshold} = round(pct * 100)` for `cityHash64(...) % 10000 < N`. Supports floats down to `0.01` (= 0.01%). |
| `--param KEY=VALUE`        | (repeatable)                            | Generic `{KEY}` placeholder substitution.                                                                                            |
| `--allow-truncated`        | `false`                                 | Without it, the command errors if the server caps the response (PostHog's `MAX_SELECT_RETURNED_ROWS=50000`).                         |
| `--s3-region`              | unset                                   | Override AWS region for S3 writes.                                                                                                   |

The CLI prints a JSON result on stdout (`output_path`, `rows`, `columns`, `project_id`, `host`) and structured logs on stderr — both agent-parseable.

## Train + predict on the resulting parquet

```bash
python -m products.automl.backend.cli run \
  --train-parquet /tmp/team_features.parquet \
  --target churned \
  --id-column user_id \
  --predictions-output /tmp/predictions.parquet \
  --eval-metric roc_auc \
  --time-limit-s 60
```

### `run` flags

| Flag                   | Default            | Notes                                                                                |
| ---------------------- | ------------------ | ------------------------------------------------------------------------------------ |
| `--train-parquet`      | (required)         | Path or `s3://` URL.                                                                 |
| `--target`             | (required)         | Target column name.                                                                  |
| `--predictions-output` | (required)         | Path or `s3://` URL for predictions parquet.                                         |
| `--id-column`          | `user_id`          | Carried through to predictions.                                                      |
| `--model-dir`          | tempdir            | Where the AutoGluon model is persisted.                                              |
| `--where`              | unset              | Optional SQL WHERE applied during parquet load (caller-controlled, no sanitization). |
| `--time-limit-s`       | `60`               | AutoGluon training budget. Set low for pipecleaning.                                 |
| `--val-fraction`       | `0.15`             | Validation fraction → AutoGluon `tuning_data`.                                       |
| `--test-fraction`      | `0.15`             | Final held-out test fraction, used only for leaderboard scoring.                     |
| `--presets`            | `medium_quality`   | AutoGluon preset.                                                                    |
| `--eval-metric`        | auto               | E.g. `roc_auc` for imbalanced targets like weekly/biweekly churn.                    |
| `--experiment-name`    | `automl-hackathon` | MLflow experiment.                                                                   |
| `--s3-region`          | unset              | Override AWS region.                                                                 |

Split semantics: shuffled 70/15/15 by default. The val frame is passed to AutoGluon as `tuning_data` (used internally for HPO + model selection / stacking). The test frame is held out completely and only used to score the final leaderboard reported in the result + MLflow. Class counts are logged on every run (`train_class_counts` in the `train_split` log line).

## Swap in real S3 data

```bash
python -m products.automl.backend.cli run \
  --train-parquet 's3://your-bucket/training/users.parquet' \
  --target churned \
  --predictions-output 's3://your-bucket/predictions/users.parquet' \
  --s3-region us-east-1
```

DuckDB authenticates via the standard AWS credential chain (env vars, `~/.aws/credentials`, IAM role). For glob patterns or partitioned datasets, point at the directory (`s3://bucket/path/`) — DuckDB's `read_parquet` accepts paths and globs.

For Postgres-resident features, instantiate `DataLoader(postgres_connection="host=… dbname=… user=… password=…")` and use `loader.query("SELECT … FROM pg.public.users JOIN read_parquet('s3://…')")` — DuckDB stitches both sources in one query.

## View MLflow runs

MLflow defaults to a local file backend at `./mlruns/`:

```bash
mlflow ui
# open http://127.0.0.1:5000
```

Each run logs: target, row counts (total/train/val/test), val and test fractions, presets, time limit, eval metric, number of features, plus per-model leaderboard metrics on the test set (`best_*`). The AutoGluon model directory and full leaderboard JSON are attached as artifacts.

To send runs to a remote tracking server, export `MLFLOW_TRACKING_URI` before running the CLI.

## Tuning levers for large-org HogQL queries

If the PostHog query 504s or hits the row cap, try in order:

1. **`--sample-pct` down**: `1.0` → `0.5` → `0.1` etc. Floats supported.
2. **Tighten the WHERE date range** in `churn_features.sql` from `INTERVAL 60 DAY` to `30` or `14`.
3. **Trim the event allowlist** if your project doesn't use mobile / survey / LLM events.
4. **Keep property-based features off** (already commented out: `clicks_pre`, `submits_pre`, `changes_pre`, `distinct_flags_pre`) — JSON extraction is the biggest per-row cost.

The PostHog public query API hard-caps results at 50,000 rows (`MAX_SELECT_RETURNED_ROWS`). The CLI defaults to fail-fast on truncated responses; pass `--allow-truncated` if you genuinely want a top-N slice.

## Next steps to productize

- **Trigger from PostHog:** wrap `run_end_to_end` in a Celery task or Temporal activity. Temporal is the better fit since training is long-running and memory-hungry.
- **Where to land predictions:** the prototype writes a flat parquet. Wiring to a team's DuckLake catalog gives you queryable predictions inside PostHog — see `posthog/ducklake/storage.py:configure_connection` and `attach_catalog` for the pattern.
- **API surface:** if you want a DRF endpoint to kick off training, run `bin/hogli product:bootstrap automl` to get the full Django app scaffold (apps.py, presentation/views.py, etc.).
- **Write predictions back to PostHog:** add a `publish-predictions` subcommand that posts results as person properties or events via the public API. Same auth pattern as `prepare-from-hogql`.
