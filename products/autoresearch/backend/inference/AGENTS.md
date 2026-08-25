# Inference

Scoring a population with the champion model and writing the result back into PostHog as `autoresearch_prediction` events.

This is the cheap, boring, high-frequency half of the product — it runs on the pipeline's cadence (default daily) for every active pipeline, forever.
`../training/` is the expensive half that produces what this package consumes.

The cardinal rule: **inference never fits.** Fitting happens once, at training completion. If you find yourself calling a `fit` here on the scoring path, something has gone wrong.

## What lives here

- `sandbox.py`
  The current path. Runs the agent-authored bundle in a Tasks sandbox, split by run type because train and predict have genuinely different data contracts:
  - `fit_champion_model()` — **train run**, called once at training completion. Materializes the _labeled_ training population, runs the bundle's `train.py`, and persists the fitted `model.pkl` next to the bundle.
  - `score_via_sandbox()` — **predict run**, called every cadence. Loads the persisted `model.pkl`, materializes _only_ the inference population (cutoff `now()`, no labels, no holdout, no fold), runs `predict.py`, and hands scores to the emitter.

  `materialize_training_data()` writes feature and label parquet files into the sandbox; `MaterializedData` carries the paths and row counts back.
  Timeouts are asymmetric on purpose — `_TRAIN_TIMEOUT_S` 300s versus `_PREDICT_TIMEOUT_S` 120s — and `_MATERIALIZE_ROW_LIMIT` caps what crosses into the sandbox.

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

- **Never re-fit on the scoring path.** `score_via_sandbox()` loads `model.pkl` and runs `predict.py` only. A fallback that quietly re-fits would make every scoring run expensive and non-deterministic.
- **Keep both champion shapes working** — bundle-backed and recipe-only. Guard on `artifact_prefix` rather than assuming.
- `validate_model_class()` must stay on the in-process path. It is not defense in depth there, it is the only defense.
- Anything that changes the cutoff, the population, or the anchor SQL belongs in `../dataset/labeling.py`, not here — training and inference share it precisely so they cannot disagree.
- A large `--backfill-days` run emits N × population events into Kafka in a tight loop and can overwhelm a local ingestion consumer. Prefer smaller backfills; a contiguous gap in prediction dates is the symptom.
- **If you change the run-type split or the event shape, update this file to match.**
