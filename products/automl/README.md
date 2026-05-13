# AutoML hackathon prototype

End-to-end pipeline: **DuckDB → Polars → AutoGluon → MLflow → predictions parquet**.

## Layout

```text
products/automl/backend/
  data/
    loader.py        # DuckDB wrapper, reads parquet (local + s3://) and Postgres
    synthetic.py     # fake per-user fixture with a binary churn target
  training/
    trainer.py       # AutoGluon TabularPredictor + MLflow tracking
  inference/
    predictor.py     # load model, predict_batch, write parquet
  pipeline.py        # run_end_to_end orchestration
  cli.py             # click commands
```

## Extra deps to install

`polars`, `duckdb`, and `pyarrow` are already pinned in `pyproject.toml`. The ML deps are not:

```bash
uv pip install autogluon.tabular mlflow
```

> `autogluon.tabular` is large (≈2 GB; pulls in LightGBM, CatBoost, XGBoost, scikit-learn, torch). Allow a few minutes on first install.

## Run end-to-end on a synthetic fixture

```bash
python -m products.automl.backend.cli generate-fixture /tmp/users.parquet --n-users 5000

python -m products.automl.backend.cli run \
  --train-parquet /tmp/users.parquet \
  --target churned \
  --predictions-output /tmp/predictions.parquet \
  --time-limit-s 60
```

The CLI prints a JSON result with `model_path`, `mlflow_run_id`, `metrics`, and `predictions_path`.

## View MLflow runs

MLflow defaults to a local file backend at `./mlruns/`:

```bash
mlflow ui
# open http://127.0.0.1:5000
```

To send runs to a remote tracking server, export `MLFLOW_TRACKING_URI` before running the CLI.

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

## Next steps to productize

- **Trigger from PostHog:** wrap `run_end_to_end` in a Celery task or Temporal activity. Temporal is the better fit since training is long-running and memory-hungry.
- **Where to land predictions:** the prototype writes a flat parquet. Wiring to a team's DuckLake catalog gives you queryable predictions inside PostHog — see `posthog/ducklake/storage.py:configure_connection` and `attach_catalog` for the pattern.
- **API surface:** if you want a DRF endpoint to kick off training, run `bin/hogli product:bootstrap automl` to get the full Django app scaffold (apps.py, presentation/views.py, etc.).
- **Person/group features:** if features need person properties or cohort membership, go through `posthog/personhog_client/` — do not query `posthog_person*` via the Django ORM.
