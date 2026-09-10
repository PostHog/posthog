# Inference

Scoring a population with the champion model and writing the result back into PostHog as `autoresearch_prediction` events.

This is the cheap, boring, high-frequency half of the product — it runs on the pipeline's cadence (default daily) for every active pipeline, forever.
`../training/` is the expensive half that produces what this package consumes.

The cardinal rule: **inference never fits.** Fitting happens once, at training completion. If you find yourself calling a `fit` here on the scoring path, something has gone wrong.

This package landed with `sandbox.py` only. `scoring.py`, `autoresearch_score`, `../presentation/`, `../temporal/`, and `../evaluation/` arrive in later pieces of the split tracked in [#88464](https://github.com/PostHog/posthog/pull/88464), so the references to them below describe where they will sit.

## What lives here

- `sandbox.py`
  The current path. Runs the agent-authored bundle in a Tasks sandbox, split by run type because train and predict have genuinely different data contracts:
  - `fit_champion_model()` — **train run**, called once at training completion. Materializes the _labeled_ training population, runs the bundle's `train.py`, runs `predict.py` once against the holdout features as a smoke test, and only then persists the fitted `model.pkl` next to the bundle. A bundle whose two scripts disagree fails here, not on the first cadence.
  - `score_via_sandbox()` — **predict run**, called every cadence. Loads the persisted `model.pkl`, materializes _only_ the inference population (cutoff `now()`, no labels, no holdout, no fold), runs `predict.py`, and hands scores to the emitter. A missing `model.pkl` fails the run.

  Both entry points validate the bundle's `features.sql` with `validate_feature_sql()` (plus no trailing `LIMIT`/`OFFSET`/`SETTINGS`) before any query runs, and run every HogQL query as the pipeline's creator (`_resolve_acting_user()`, or the explicit `user` a management command passes), with `CALCULATE_BLOCKING_ALWAYS` so a cadence never reuses a cached population, and with `LABELER_QUERY_MODIFIERS`, because the anchor SQL reads `person.is_identified` and only resolves under that persons-on-events mode.
  The train run persists `feature_columns.json` next to `model.pkl`; every predict run sends exactly those columns, in that order, filling an absent or null one with zeros, so the fitted model never sees a column set that depends on today's population. A champion fitted before the file existed falls back to deriving the columns from the scoring rows. A fitted column that holds a present non-numeric value fails the run, because the persisted list bypasses `_numeric_feature_cols()` and zero-filling schema drift would emit a plausible wrong prediction.
  `materialize_training_data()` writes feature and label parquet files into the sandbox; `MaterializedData` carries the paths and row counts back. Materialized rows must key exactly one person each (`validate_unique_distinct_ids()`), and a training row whose label failed to join fails the run. Feature SQL that returns two columns of the same name fails the run, because `HogQLResult.as_dicts()` keeps only the last value of a repeated name.
  Every upload goes through `_write_file()`, which fails the run on a non-zero result: the providers report a failed write through the exit code rather than an exception, and a discarded result would let a script run against a missing input. The train run's smoke test loads the model bytes read back from the sandbox, written to `_SMOKE_MODEL_PKL`, so the bytes the caller persists are the bytes `predict.py` proved it can load.
  Everything a script produces is untrusted: script output goes to `data/script.log` and only a bounded tail comes back on failure; every file readback is size-gated inside the sandbox (`_MAX_READBACK_BYTES`, the artifact cap), emits at most cap-plus-one bytes through `head -c` however the file grows, and fails on a missing, empty, or oversized file; `output.json` values are typed and ranged; `scores.parquet` is checked from its footer before it is decoded (column types, row count against the input, decoded byte size of the two contract columns against the cap), only those two columns are read, and a person scored twice fails the run.
  Timeouts are asymmetric on purpose — `_TRAIN_TIMEOUT_S` 300s versus `_PREDICT_TIMEOUT_S` 120s — with `_SANDBOX_TTL_S` as the backstop for a worker that dies mid-run. `_MATERIALIZE_ROW_LIMIT` and `_MAX_FEATURE_COLS` together cap what crosses into the sandbox: the row cap alone does not bound the matrix the worker expands, because the agent's SQL chooses the column count.

- `scoring.py`
  The legacy in-process path plus the event emission that both paths share.
  `run_inference_for_pipeline()` is the entry point called by the Temporal activity and by `autoresearch_score`.
  This is the only place that resolves `model_class` through `importlib`, so it is the one genuine code-execution surface — it calls `validate_model_class()` from `../training/recipe_validation.py` before importing. Do not weaken that.
  `_resolve_distinct_ids()` maps the `person_id` everything is keyed on back to a `distinct_id` for the emitted event.

## The emitted event

```text
event:       autoresearch_prediction
distinct_id: <person distinct_id>
properties:  $autoresearch_pipeline_id, $autoresearch_p_y, ...
```

One event per scored person per run. This is the product's actual output — the person property on the pipeline (`output_person_property`, e.g. `predicted_p_downloaded_file_30d`) is derived from these.

Because emission goes through normal ingestion, backdated scoring (`--prediction-date` / `--backfill-days`) is silently dropped when the team has `drop_events_older_than_seconds` set. The events never arrive and nothing errors.

## Mental model

1. Load the champion for the pipeline.
2. Resolve the inference population and build anchors at cutoff `now()` (`../dataset/labeling.py`).
3. If the champion has an `artifact_prefix`, materialize features into a sandbox and run `predict.py`. Otherwise compile the recorded recipe and score in-process.
4. Map `person_id` → `distinct_id` and emit one event each.
5. Record an `AutoresearchRun` for the execution.

Both model shapes are live and must stay that way: bundle-backed champions take the sandbox path, older recipe-only champions take the in-process path.

## The failure mode that will cost you a day

**A uniform or constant score distribution is an identifier mismatch, not a bad model.**

Everything is keyed on `person_id`, one row per person — the agent's `feature_sql`, the label query, and the population query all have to agree.
When they don't, nothing raises: labels fail to join, come back all-zero, the model degenerates, and every person gets the same score. A raw UUID leaking into the event path also breaks JSON serialization and emits zero events.

Before suspecting the model, check that features, labels, and population all key on `person_id` and coerce to `str`.

## Where the rest of the system meets this package

- **Scheduled by** — `AutoresearchInferenceWorkflow` and `activity_run_inference` in `../temporal/workflows.py`.
- **Run headlessly by** — `autoresearch_score` (see `../management/AGENTS.md`), which calls the same functions directly.
- **Called by training** — `fit_champion_model()` is invoked from the completion path in `../training/promotion.py`. It lives here because it shares the materialization and sandbox machinery with scoring, not because it is part of the inference loop.
- **Reads** — `AutoresearchModel` (champion role) and the bundle in object storage via `../training/artifacts.py`.
- **Feeds** — `../evaluation/online_validation.py`, which reads the emitted events back once their horizon has elapsed.
- **Population and anchors** — `../dataset/labeling.py`, shared with training so the cutoff contract cannot drift.

## When editing this flow

- **Never re-fit on the scoring path.** `score_via_sandbox()` loads `model.pkl` and runs `predict.py` only. A fallback that quietly re-fits would make every scoring run expensive and non-deterministic, and concurrent cadences would race to overwrite the pickle. A missing model is a failed run.
- **Keep both champion shapes working** — bundle-backed and recipe-only. Guard on `artifact_prefix` rather than assuming.
- `validate_model_class()` must stay on the in-process path. It is not defense in depth there, it is the only defense.
- Anything that changes the cutoff, the population, or the anchor SQL belongs in `../dataset/labeling.py`, not here — training and inference share it precisely so they cannot disagree.
- Nothing a script writes reaches the worker unbounded. Keep the size gate in `_readback_command()` and the log redirect in `_script_command()` when you add a new file to the contract.
- The sandbox providers differ: Modal honors `block_network`; the Docker provider (local dev) does not, and mounts `SANDBOX_REPO_MOUNT_MAP` checkouts read-write. The no-egress guarantee holds in production only. Hogland maps only `DEFAULT_BASE`, so this workload does not run there.
- A large `--backfill-days` run emits N × population events into Kafka in a tight loop and can overwhelm a local ingestion consumer. Prefer smaller backfills; a contiguous gap in prediction dates is the symptom.
- **If you change the run-type split or the event shape, update this file to match.**
