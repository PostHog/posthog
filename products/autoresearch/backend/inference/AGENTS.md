# Inference

Scoring a population with the champion model and writing the result back into PostHog as `autoresearch_prediction` events.

This is the cheap, boring, high-frequency half of the product — it runs on the pipeline's cadence (default daily) for every active pipeline, forever.
`../training/` is the expensive half that produces what this package consumes.

The cardinal rule: **inference never refits a persisted model.** A bundle is fitted once, at training completion, and every cadence loads that `model.pkl`. A recipe-only champion has no persisted model, so it fits its allowlisted sklearn class in process on every cadence; that is the cost of a champion without a bundle, not a refit.

This package landed ahead of its callers. `../presentation/`, `../temporal/`, and `../evaluation/` arrive in later pieces of the split tracked in [#88464](https://github.com/PostHog/posthog/pull/88464), so the references to them below describe where they will sit.

## What lives here

- `sandbox.py`
  The current path. Runs the agent-authored bundle in a Tasks sandbox, split by run type because train and predict have genuinely different data contracts:
  - `fit_champion_model()` — **train run**, called once at training completion. Materializes the _labeled_ training population, runs the bundle's `train.py`, runs `predict.py` once against the holdout features as a smoke test, and only then persists the fitted `model.pkl` next to the bundle. A bundle whose two scripts disagree fails here, not on the first cadence.
  - `score_via_sandbox()` — **predict run**, called every cadence. Loads the persisted `model.pkl`, materializes _only_ the inference population (cutoff at the start of the prediction date, no labels, no holdout, no fold), runs `predict.py`, and hands scores to the emitter. A missing `model.pkl` fails the run.

  Both entry points validate the bundle's `features.sql` with `validate_feature_sql()` (plus no trailing `LIMIT`/`OFFSET`/`SETTINGS`) before any query runs, and run every HogQL query as the pipeline's creator (`_resolve_acting_user()`, or the explicit `user` a management command passes), with `CALCULATE_BLOCKING_ALWAYS` so a cadence never reuses a cached population, and with `LABELER_QUERY_MODIFIERS`, because the anchor SQL reads `person.is_identified` and only resolves under that persons-on-events mode.
  The train run persists `feature_columns.json` next to `model.pkl`; every predict run sends exactly those columns, in that order, filling an absent or null one with zeros, so the fitted model never sees a column set that depends on today's population. A champion fitted before the file existed falls back to deriving the columns from the scoring rows. A fitted column that holds a present non-numeric value fails the run, because the persisted list bypasses `_numeric_feature_cols()` and zero-filling schema drift would emit a plausible wrong prediction.
  `materialize_training_data()` writes feature and label parquet files into the sandbox; `MaterializedData` carries the paths and row counts back. Materialized rows must key exactly one person each (`validate_unique_distinct_ids()`), and a training row whose label failed to join fails the run. Feature SQL that returns two columns of the same name fails the run, because `HogQLResult.as_dicts()` keeps only the last value of a repeated name.
  Every upload goes through `_write_file()`, which fails the run on a non-zero result: the providers report a failed write through the exit code rather than an exception, and a discarded result would let a script run against a missing input. The train run's smoke test loads the model bytes read back from the sandbox, written to `_SMOKE_MODEL_PKL`, so the bytes the caller persists are the bytes `predict.py` proved it can load.
  Everything a script produces is untrusted: script output goes to `data/script.log` and only a bounded tail comes back on failure; every file readback is size-gated inside the sandbox (`_MAX_READBACK_BYTES`, the artifact cap), emits at most cap-plus-one bytes through `head -c` however the file grows, and fails on a missing, empty, or oversized file; `output.json` values are typed and ranged; `scores.parquet` is checked from its footer before it is decoded (column types, row count against the input, decoded byte size of the two contract columns against the cap), only those two columns are read, and a person scored twice fails the run.
  Timeouts are asymmetric on purpose — `_TRAIN_TIMEOUT_S` 300s versus `_PREDICT_TIMEOUT_S` 120s — with `_SANDBOX_TTL_S` as the backstop for a worker that dies mid-run. `_MATERIALIZE_ROW_LIMIT` and `_MAX_FEATURE_COLS` together cap what crosses into the sandbox: the row cap alone does not bound the matrix the worker expands, because the agent's SQL chooses the column count.

- `scoring.py`
  The recipe-only in-process path plus the event emission that both paths share.
  `run_inference_for_pipeline()` is the entry point called by the Temporal activity and by `autoresearch_score`; `score_population()` is the scoring half alone, which the command's dry run calls so it exercises the same route as a real run; the prediction-date guards run inside it, so the dry run refuses exactly the dates the live run refuses.
  A recipe-only champion routes on its recipe: a stub recipe (`stub: true`, SQL evaluated at `now()`) scores by the fixed engagement formula, with the inference population applied inside its query so the row bound measures the population and not the team, and its rows checked against the population count; an agent recipe goes through `validate_runnable_feature_sql()` like a bundle (so a trailing `LIMIT` or an `{anchors}` that sits only in a comment fails the run rather than running without a cutoff) and then fits on the anchored training rows and predicts on the inference anchors. Neither can be backfilled: the fit happens at scoring time on labels decided as of `now()`, so a fit for a past date would learn from outcomes after it. Only a bundle, whose `model.pkl` already exists, is re-scored in the past. The recipe fit validates its training rows the way the sandbox does (one row per person, every row labeled, at most `_MAX_FEATURE_COLS` numeric columns, no duplicate column names), sorts them by person before fitting, because an estimator that samples row indices fits a different model on a different row order despite its seed, seeds a stochastic estimator from the pipeline id unless the recipe sets `random_state`, so a retry refits the same model under the same event UUIDs, and pins `n_jobs=1`, because the fit runs in the worker process. Its probabilities keep full precision, as the bundle path's do.
  This is the only place that resolves `model_class` through `importlib`, so it is the one genuine code-execution surface — it calls `validate_model_class()` from `../training/recipe_validation.py` before importing. Do not weaken that.
  Every query runs as the acting user (the pipeline's creator, or the `--user-id` a command passes), with an explicit bound and a truncation check, including the identity lookup: a bare `SELECT` that HogQL caps at 100 rows would emit most of the population person-less. Every result is refused above `_MAX_FEATURE_COLS` output columns as it is read, before any column is typed, because the numeric filter would otherwise discard the excess only after it was materialized. A run decides its dates once, in `ScoringWindow`: live or backfill, the cutoff every query binds to, and the emit timestamp. The cutoff is the start of the prediction date in UTC for every run, live included, so a retry recomputes the population the failed attempt had (the event UUIDs are the same either way), the feature query and the anchor count agree, and a backfill of a date gets the anchors a live run on that date got. A run that crosses midnight keeps the mode it started in.
  Inference rows are checked against the anchor count on both paths (`count_inference_anchors()`), and training rows against the labeled anchor count (`count_training_anchors()`), because feature SQL that inner joins or filters a joined table in `WHERE` drops people without any row looking wrong.
  `_resolve_distinct_ids()` maps the `person_id` everything is keyed on back to one current `distinct_id` through personhog (`get_persons_by_uuids`), never from event history, because an id read off old events can belong to someone else after a merge or split.

## The emitted event

```text
event:       autoresearch_prediction
distinct_id: <person distinct_id>
properties:  $autoresearch_pipeline_id, $autoresearch_p_y, ...
```

One event per scored person per run, sent as one `capture_batch_internal()` batch. This is the product's actual output — the person property on the pipeline (`output_person_property`, e.g. `predicted_p_downloaded_file_30d`) is derived from these.
Any event the batch does not accept, or accepts with a warning (capture stores the event but has switched something off, such as person processing for a rate-limited distinct id, so the `$set` never lands), fails the run: the event UUIDs are deterministic per (pipeline, model, date, person), so the retry re-sends every row and ingestion keeps one copy, whereas completing with a partial batch would advance the cadence past the people who never received their prediction.
Right before the batch goes out the run re-reads the model's role and fails if promotion has replaced the champion meanwhile, so a superseded model does not write its `$set` over the new champion's. The window between that read and capture is what remains of the race.

Because emission goes through normal ingestion, a backdated event older than the team's `drop_events_older_than` is accepted by capture and then dropped, so a run refuses a backfill past that threshold instead of recording rows nobody can read. A run also refuses a future prediction date, and a backfill of a population filtered on person properties, because those properties are evaluated as they are today.

The prediction event is itself an event on the person, so every live cadence adds one. The population and anchor scans in `../dataset/labeling.py` exclude it; feature SQL is the agent's, so the fixture's `features.sql` excludes it explicitly and the agent brief says to.

## Mental model

1. Load the champion for the pipeline.
2. Resolve the inference population and build anchors at the cutoff, the start of the prediction date in UTC (`../dataset/labeling.py`).
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

- **Never re-fit a persisted model on the scoring path.** `score_via_sandbox()` loads `model.pkl` and runs `predict.py` only. A fallback that quietly re-fits would make every scoring run expensive and non-deterministic, and concurrent cadences would race to overwrite the pickle. A missing model is a failed run. The in-process fit in `scoring.py` is the recipe-only shape's contract, not a fallback, and it must not be reached for a model that has an `artifact_prefix`.
- **Keep both champion shapes working** — bundle-backed and recipe-only. Guard on `artifact_prefix` rather than assuming.
- `validate_model_class()` must stay on the in-process path. It is not defense in depth there, it is the only defense.
- Anything that changes the cutoff, the population, or the anchor SQL belongs in `../dataset/labeling.py`, not here — training and inference share it precisely so they cannot disagree.
- Nothing a script writes reaches the worker unbounded. Keep the size gate in `_readback_command()` and the log redirect in `_script_command()` when you add a new file to the contract.
- The sandbox providers differ: Modal honors `block_network`; the Docker provider (local dev) does not, and mounts `SANDBOX_REPO_MOUNT_MAP` checkouts read-write. The no-egress guarantee holds in production only. Hogland maps only `DEFAULT_BASE`, so this workload does not run there.
- A large `--backfill-days` run emits N × population events into Kafka in a tight loop and can overwhelm a local ingestion consumer. Prefer smaller backfills; a contiguous gap in prediction dates is the symptom.
- **If you change the run-type split or the event shape, update this file to match.**
