# Evaluation

Did the predictions actually come true?

Training measures a model against a holdout slice of history. This package measures it against reality: once a prediction's horizon has elapsed, it joins the emitted `autoresearch_prediction` events back to what the person actually did and computes realized performance.

It is the only honest number in the product. A holdout AUC of 0.93 says the model separates history well; the realized AUC says whether it predicted the future.

This package landed ahead of its callers. `../presentation/` and `../temporal/` arrive in later pieces of the split tracked in [#88464](https://github.com/PostHog/posthog/pull/88464), so the references to them below describe where they will sit.

## What lives here

- `online_validation.py`
  `run_online_validation_for_pipeline()` is the entry point, called by the Temporal validation activity and by the `autoresearch_validate_online` command. It takes the acting `user` HogQL applies access control for, defaulting to the pipeline's creator.

  Per matured prediction date, per model that emitted predictions, it computes:
  - **realized AUC** — ranking quality against actual outcomes (needs both classes; a single-class date records `single_class_no_auc` instead)
  - **Brier score** — squared error of the probabilities
  - **expected calibration error** (`_expected_calibration_error`, 10 bins) — whether "0.8" really means 80%
  - **lift@k** (`_lift_at_k`) — how much better than random the top slice is; ties at the boundary score are split fractionally so the number does not depend on row order

  Every model that emitted predictions on the date is scored, whatever its role now. Inference emits the champion only today; when challenger shadow scoring ships, their realized numbers land here without a change, which is what makes challenger promotion decidable on evidence rather than on holdout alone.
  Results land on `AutoresearchModel.realized_score` / `.calibration_error` / `.metrics["realized"]` via `_update_model_realized_metrics()`, and each validated date records an `AutoresearchRun` whose `metrics["per_model"]` keeps the emitted role next to the current one.

## Mental model

```text
completed inference run for day D  (metrics: prediction_date, horizon_days, rows_scored)
        │
        │  ... wait horizon_days ...
        │
 D + horizon 00:00 UTC + grace <= now  →  the outcome window has closed and its last events have landed
        │
 find_pending_validation_dates  →  matured (date, horizon) groups whose validation does not match their inference runs
        │
 _claim_date (RUNNING run, under the pipeline row lock)
        │
 _fetch_predictions  ×  _fetch_realized_labels  →  metrics per model  →  one transaction
```

Candidate dates come from Postgres, not from a scan of the events table: the inference runs record the prediction date and the horizon they scored against, so a daily pass costs nothing for the dates it does not validate, and the horizon used is the one the predictions were made under.

`find_pending_validation_dates()` is what keeps this idempotent. A group is done once a `COMPLETED` validation run holds the same per-model counts as the group's inference runs, so the workflow can run daily without recomputing history, and a later rescore or a new model on the date makes the group pending again and replaces its evidence. A `FAILED` run does not count, so its group is retried. A `RUNNING` validation claim, and a `RUNNING` inference run, hold the group only while younger than `STALE_RUN_AFTER`, so a worker killed mid-run cannot block it forever. Models scored on one date under different horizons are separate groups with their own outcome windows. Maturity waits `OUTCOME_INGESTION_GRACE` past the window end so the last outcome events have reached ClickHouse.

Both ClickHouse queries are bounded by what the inference runs say was emitted. The prediction fetch must return exactly `rows_scored` persons per model; fewer means ingestion has not caught up with a backfill, more means events the run did not emit, and either fails the date so it is retried instead of completing with wrong numbers. The realized-label scan is restricted to the predicted persons, and its window is the UTC one scoring bound the run to (`[D 00:00, D + horizon 00:00)`). Before the group is marked complete, its inference runs are read again inside the transaction: a run that finished or started while the queries ran fails the group, and a run that slips in after that check changes the counts and makes the group pending again on the next pass. The model rows are locked for the write, so two validators on different dates cannot race the newest-date guard.

All the heavy work — the HogQL queries and the sklearn metrics — happens inside a single Temporal activity. Nothing large crosses a workflow boundary, which is deliberate: activity payloads are capped, and prediction sets are big.

## Things that bite

- **Nothing to validate on day one.** Predictions written today mature in `horizon_days`. A fresh pipeline returns zero validated dates and that is correct, not a bug.
  To get a populated view locally, backdate: `autoresearch_score --prediction-date <past>` or `--backfill-days N` emits already-matured predictions.
- **A backfill's date fails validation until its events are all in ClickHouse.** The fetch compares against the run's `rows_scored`, so a pass that runs seconds after a backfill records a `FAILED` run and the next pass picks the date up.
- **Backdated events are refused by scoring when the team sets `drop_events_older_than_seconds`**, so no inference run is recorded and validation has nothing to look for.
- **A deleted model takes its evidence with it.** Its inference runs lose their model and drop out of the candidates, and its prediction events are not fetched. A model deleted mid-validation is recorded in the run's `per_model` as `deleted` and skipped for the model update, and its absence does not reopen the group.
- **A completed date is never revisited.** An outcome event that reaches ClickHouse more than `OUTCOME_INGESTION_GRACE` after the window closed (an offline SDK buffer flushed days late) reads as a negative in the stored metrics.
- **Only the AUC needs both classes.** An all-negative day still records Brier, calibration error, and lift, which is where calibration matters for a rare target.

## Where the rest of the system meets this package

- **Scheduled by** — `AutoresearchValidationWorkflow` / `activity_run_validation` in `../temporal/workflows.py`.
- **Run headlessly by** — `autoresearch_validate_online` (see `../management/AGENTS.md`), which supports `--dry-run` and `--user-id`, and exits non-zero when a date fails.
- **Reads** — `autoresearch_prediction` events emitted by `../inference/`, the `prediction_date` / `horizon_days` keys `scoring.py` records on each inference run, and the target condition from `../dataset/labeling.py` (`build_target_condition`) so "did it happen?" is defined identically to how it was labeled at training time. The product's own prediction event is excluded from the outcome scan, as it is from the labeler's.
- **Writes** — realized metrics onto `AutoresearchModel`, plus an `AutoresearchRun` per validated date.
- **Not to be confused with** `../dataset/validation.py`, which is pre-flight target viability. Same word, opposite ends of the lifecycle.

## When editing this flow

- **Reuse `build_target_condition()` from `../dataset/labeling.py`.** If realized outcomes were defined differently from training labels, every realized metric would be measuring a different question than the model was trained on.
- Keep `find_pending_validation_dates()` the only date selector, and keep the claim under the pipeline row lock, so validation stays idempotent and safe to run from the schedule and the command at once. A validation run's `per_model` entry carries each model's `n_scored`, which is what marks a group validated; keep writing it.
- Keep every query bounded by the inference runs' counts. A bare HogQL SELECT is capped at 100 rows without an error.
- Keep the model updates and the run write in one transaction, so a failure part-way leaves no model with a score its run does not record.
- Keep the heavy work inside one activity. Returning prediction sets through the workflow would hit the Temporal payload limit as soon as a pipeline scores a real population.
- **If you add a metric or change the maturity rule, update this file to match.**
