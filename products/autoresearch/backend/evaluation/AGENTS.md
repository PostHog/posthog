# Evaluation

Did the predictions actually come true?

Training measures a model against a holdout slice of history. This package measures it against reality: once a prediction's horizon has elapsed, it joins the emitted `autoresearch_prediction` events back to what the person actually did and computes realized performance.

It is the only honest number in the product. A holdout AUC of 0.93 says the model separates history well; the realized AUC says whether it predicted the future.

## What lives here

- `online_validation.py`
  `run_online_validation_for_pipeline()` is the entry point, called by the Temporal validation activity and by the `autoresearch_validate_online` command.

  Per matured prediction date, per model, it computes:
  - **realized AUC** — ranking quality against actual outcomes
  - **Brier score** — squared error of the probabilities
  - **expected calibration error** (`_expected_calibration_error`, 10 bins) — whether "0.8" really means 80%
  - **lift@k** (`_lift_at_k`) — how much better than random the top slice is

  Champions and challengers are both scored, which is what makes challenger promotion decidable on evidence rather than on holdout alone.
  Results land on `AutoresearchModel.realized_score` / `.calibration_error` / `.metrics` via `_update_model_realized_metrics()`, and each validated date records an `AutoresearchRun`.

## Mental model

```text
predictions emitted on day D
        │
        │  ... wait horizon_days ...
        │
 D + horizon <= today  →  the label is now knowable
        │
 _find_mature_unvalidated_dates  →  dates with predictions but no validation run
        │
 _fetch_predictions_by_model  ×  _fetch_realized_labels  →  metrics per model
```

`_find_mature_unvalidated_dates()` is what keeps this idempotent: it only picks up dates whose horizon has passed _and_ which have not already been validated, so the workflow can run daily without recomputing history.

All the heavy work — the HogQL queries and the sklearn metrics — happens inside a single Temporal activity. Nothing large crosses a workflow boundary, which is deliberate: activity payloads are capped, and prediction sets are big.

## Things that bite

- **Nothing to validate on day one.** Predictions written today mature in `horizon_days`. A fresh pipeline returns zero validated dates and that is correct, not a bug.
  To get a populated view locally, backdate: `autoresearch_score --prediction-date <past>` or `--backfill-days N` emits already-matured predictions.
- **Backdated events are silently dropped when the team sets `drop_events_older_than_seconds`.** Ingestion discards them as too old, so validation finds nothing and nothing errors anywhere.
- **A contiguous gap in prediction dates means the backfill lost a chunk**, not that validation skipped it — a large backfill can overwhelm the local ingestion consumer.

## Where the rest of the system meets this package

- **Scheduled by** — `AutoresearchValidationWorkflow` / `activity_run_validation` in `../temporal/workflows.py`.
- **Run headlessly by** — `autoresearch_validate_online` (see `../management/AGENTS.md`), which supports `--dry-run`.
- **Reads** — `autoresearch_prediction` events emitted by `../inference/`, and the target condition from `../dataset/labeling.py` (`build_target_condition`) so "did it happen?" is defined identically to how it was labeled at training time.
- **Writes** — realized metrics onto `AutoresearchModel`, plus an `AutoresearchRun` per validated date.
- **Not to be confused with** `../dataset/validation.py`, which is pre-flight target viability. Same word, opposite ends of the lifecycle.

## When editing this flow

- **Reuse `build_target_condition()` from `../dataset/labeling.py`.** If realized outcomes were defined differently from training labels, every realized metric would be measuring a different question than the model was trained on.
- Keep `_find_mature_unvalidated_dates()` the only date selector, so validation stays idempotent and safe to run on a schedule.
- Keep the heavy work inside one activity. Returning prediction sets through the workflow would hit the Temporal payload limit as soon as a pipeline scores a real population.
- Score challengers as well as the champion — challenger realized performance is the evidence promotion should eventually rest on.
- **If you add a metric or change the maturity rule, update this file to match.**
