# Inbox ranking training examples

The tabular, report-embedding and title-embedding ranking families use one example per report per head, from the report's birth-day snapshot.
This prevents long-lived reports from receiving more weight in training because they appear in more daily snapshots.
Birth days use the UTC interval returned by `snapshot_bounds`, including the start and excluding the end.
The label comes from the snapshot `horizon_days` later, including outcomes already present on the birth day.

The `pr_merged` head includes every report and reads merges within 14 days.
The `dismiss_wrong` head includes impressed reports and reads wrong-dismissal outcomes within 14 days.

The examples asset records `reports_missing_birth_snapshot` for observed reports born inside the lookback whose birth-day partition is missing.
These reports produce no birth-grain example; reports born before the lookback do not contribute to this count.
A missing horizon snapshot also prevents an example because its label is unknown.
Point-in-time state, label provenance, and embedding availability checks still apply.
Each embedding family reads its own rendering's snapshot, so a report missing from one snapshot is an example for the other family only.

Every training series resets on the first partition after deploy.
Before and after holdout numbers are not comparable because the example population changes.
The daily snapshots and selectable scoring-moment and report grains remain available for future models.

See the [ranking DAG README](../../products/signals/dags/inbox_ranking/README.md) for the feature-set contract and operating instructions.

## What each probability means

Each head is conditioned on its cohort (`training/heads.py`).
The cohort is read at the horizon snapshot, so "shown" means shown at any time before the horizon.
`p_open` and the other cohort-conditioned heads are not unconditional probabilities.
Each head is graded only on its cohort.

| Head            | Probability                            | Horizon |
| --------------- | -------------------------------------- | ------- |
| `open`          | P(opened \| shown)                     | 3d      |
| `action`        | P(create-PR click or discuss \| shown) | 7d      |
| `discuss`       | P(discuss \| shown)                    | 7d      |
| `dismiss_wrong` | P(dismissed as wrong \| shown)         | 14d     |
| `reviewer_fix`  | P(reviewers corrected \| shown)        | 14d     |
| `thumbs_up`     | P(thumbs up \| opened)                 | 7d      |
| `pr_created`    | P(PR created) over every report        | 7d      |
| `pr_merged`     | P(PR merged) over every report         | 14d     |
| `refund`        | P(refund) over every report            | 14d     |

Each head in `metadata.json` records `cohort` (`impressed`, `opened` or `everyone`) and `horizon_days`.

## Row budget

A feature set can limit the rows one head keeps (`max_examples_per_head`).
The embedding families set it to 100,000; the tabular family has no budget.
The budget limits history, not the rows inside a day:

- The head's examples are grouped by report-creation day, newest first.
- Whole days are kept while the running total stays within the budget, and every older day is dropped.
- The newest day is always kept, even when it alone exceeds the budget.

Every kept day keeps all of its positives and negatives, so the kept label rate is the population rate of those days.
The scores stay calibrated to that population, and the holdout stays a clean time split.
A recency cut drops old positives with old negatives, so the budget must stay large enough to keep the rare heads fed.

Each head in `metadata.json` records `example_window_start`, the earliest report-creation day kept, and `example_cap_bound`, whether the budget dropped any day.
`inbox_ranking_examples_built` carries both fields, so a chart shows when the budget starts to bind.

## Promotion

A candidate replaces its family's champion only when, on every head the champion could read:

- its holdout AUC is at most `AUC_TOLERANCE` below the champion's, and
- its holdout calibration error (ECE) is at most `ECE_TOLERANCE` above the champion's.

Both champion numbers come from the champion's `<head>.holdout.ubj` scored on the candidate's holdout.
A head without a paired champion ECE skips the calibration check.
`inbox_ranking_promotion_decided` carries the paired values as `champion_<head>_auc_on_this_holdout` and `champion_<head>_ece_on_this_holdout`.

## Baked and unbaked unseen metrics

`inbox_ranking_unseen_graded` evaluates the saved predictions for each scoring cohort every day, from its birth-day snapshot through each head's horizon.
It reads each scores partition once per run and never re-scores an older cohort with a newer model.
The first read has `observed_days=0`; the unit is the difference between UTC snapshot dates, not a full day of observation for every report.

- **Baked:** `inbox_ranking_unseen_head_graded`, `inbox_ranking_unseen_calibration`, and `inbox_ranking_unseen_report_graded` retain their full-horizon semantics.
- **Daily evaluations:** `inbox_ranking_unseen_head_evaluated` carries the head metrics at each observation age, including the final baked evaluation. Filter `is_mature=false` for unbaked results and `is_mature=true` for baked results.

The daily event includes `scoring_partition`, `evaluation_partition`, `observed_days`, `horizon_days`, `is_mature`, and `evaluated_at`, alongside the model family, version, role and pool.
`rows` counts eligible reports, `scored_rows` counts the original scored reports, and `cohort_coverage` is their ratio.
Eligibility can grow as reports receive impressions or opens; label availability and provenance rules still apply.
Missing scores or required label columns produce an explicit skip in the asset metadata, not an all-negative grade.
An empty eligible cohort emits zero rows and null metrics; a cohort with only one outcome class emits counts and a null AUC.
`readable` continues to describe the model's holdout readability, independently of maturity or the evaluation's sample size.

### Reading the two versions

For a cohort-date time series, group by `(scoring_partition, pool, head, model_name, model_version, model_role)`.
Select the complete event with the greatest `(evaluation_partition, evaluated_at)` in each group, rather than averaging or summing daily revisions.
Use `run_id` as a tie-breaker for an identical evaluation timestamp.
Select the complete event even when its AUC is null, so a previously defined AUC does not hide an empty or single-class revision.
Plot `scoring_partition` on the x-axis and distinguish the unbaked tail with `is_mature`.
Keep cohort age, horizon, rows and positives visible in the tooltip.
The event timestamp remains the evaluation partition's midday UTC, so default event-time trends describe the evaluation day rather than the scoring cohort.

For a history at a fixed age, filter `observed_days` first and retain the newest `evaluated_at` for each group.
For example, compare day-one cohorts with other day-one cohorts, while keeping the baked series alongside them.
Model comparisons need the same reports, observation age and pool.
The daily stream contains aggregate metrics only; per-report and per-decile events remain baked-only to bound telemetry volume.

An unbaked negative means the outcome has not happened in the available snapshot.
Later outcomes can move AUC in either direction, and early evaluations can favor reports whose outcomes arrive quickly.
Early calibration error compares a full-horizon prediction with incomplete outcomes; use baked results for calibration decisions and definitive regression judgments.
Daily evaluations do not change training labels, champion promotion or serving.
They stop at the head's horizon; a retry evaluates the named snapshot rather than extending that horizon to the retry date.

### Verification after deployment

Check that the new event has an age-zero evaluation for each scored head and subsequent evaluations through its horizon.
For the final evaluation, compare counts and metrics with the matching baked event.
Check missing-partition metadata and grading runtime; the grader reads at most `max(horizon_days) + 1` scores objects per run.
Existing baked-only consumers need no filter changes.
New charts must opt into the daily event and select one revision per cohort as described above.

## Classification metrics

Every fitted head reports classification metrics next to AUC and calibration.
They answer two questions: of the reports a head flags, how many have the outcome (precision), and of the outcomes, how many the head flags (recall).

### Threshold

A head predicts positive when `score >= classification_threshold`.
A score equal to the threshold is a positive prediction.
The threshold is the positive rate of the rows the booster was fit on.
It means "at least as likely as the average fitting example", not a 50% probability.

- **Holdout:** the threshold is the positive rate of the train-only rows. It is fixed before the holdout outcomes are read.
- **Unseen:** the threshold is the positive rate of every row the refit was fit on. The candidate saves it per head as `refit_classification_threshold` in `metadata.json`. The scorer copies it onto each saved score as `classification_threshold`, and every daily and mature grade of those scores reads that value.
- A champion keeps its own threshold. A candidate and a champion graded on the same reports use different cuts.

The threshold is specific to the head, family, version and fitting population.
A row budget keeps only the newest report-creation days, so the rate is that window's rate, not the rate of the full lookback.
Do not read the threshold as population prevalence, and do not compute it again from evaluation labels.

### Metrics

The metrics use the same eligible rows as the other metrics of the grade.

- Counts: `true_positives`, `false_positives`, `true_negatives`, `false_negatives`.
- Ratios: `precision`, `recall`, `f1`, `specificity`, `accuracy`, `balanced_accuracy` (the mean of recall and specificity), `predicted_positive_rate`.
- `inbox_ranking_candidate_trained` carries them with a `holdout_` prefix, plus `refit_classification_threshold`.
- `inbox_ranking_unseen_head_graded` and `inbox_ranking_unseen_head_evaluated` carry them without a prefix.

Null values have three causes:

- A ratio with a zero denominator is null. For example, a cohort without positives has a null recall.
- An empty cohort with a known threshold has zero counts and null ratios.
- A model or scores object saved before thresholds existed has null classification fields. Its other metrics stay.

Readability and maturity rules do not change.
An unbaked negative can still become a positive, so unbaked precision and recall are provisional.
These metrics are evaluation-only: they do not change inbox order or champion promotion.

### Pooling

Read families and maturity levels apart.
To pool cohorts or days, select one revision per cohort as described in [Reading the two versions](#reading-the-two-versions), sum the confusion counts, and then compute the ratios from the sums.
Never average daily precision, recall or F1.
A pooled line over several versions uses the frozen threshold of each version, so label it that way.

After deployment and a new training and scoring run, check that the candidate events carry numeric `holdout_` fields and `refit_classification_threshold`, and that the unseen events carry `classification_threshold`.
Check the mature grades as each head's horizon becomes available.

## Served-model classification metrics

The unseen grades rescore the newborn pool with the day's candidate and champion.
They are not the scores the inbox served.
The served grade closes that gap.

### Score events

Each `inbox_ranking_report_scored` event carries the served threshold of its model:

- `threshold_<head>`: the head's `refit_classification_threshold` from the serving copy's metadata. A serving copy is immutable per model key, so this is the threshold that scored the report.
- `predicted_<head>`: `p_<head> >= threshold_<head>`. A score equal to the threshold is a positive prediction.
- `readable_heads`: the heads whose holdout was readable.

A head without a saved threshold has no `threshold_` or `predicted_` property.
Models trained before thresholds existed have none, and no other value stands in for one.

### The served grade

`inbox_ranking_served_scores` writes `inbox_ranking_served_scores/v1/dt=D/` in the unseen scores schema.

- Population: D's newborn pool, the same reports the unseen grade covers.
- Score: the earliest scored event in D with the `served` role and this deployment's `environment`.
- `classification_threshold` comes from `threshold_<head>`, and is null when the event has none.
- Asset metadata: `served_pool_coverage`, rows per model version, and the heads without a threshold.

`inbox_ranking_unseen_graded` reads the served object next to the unseen object for each scoring partition.
Its events then carry `model_role = 'served'`, with no new event type.
A missing served object is a skip in the asset metadata, not a failure.

Caveats:

- The daily promotion can change the served model part of the way through D, so one day's cohort can split across two versions. Grades stay per `(model_name, model_version, model_role)`. Never pool them across versions.
- A report first scored after D ends, for example when its vector arrived late, is not in D's served rows. `served_pool_coverage` shows this. A later score never fills it in.
- The sweep scores with the vector current at scoring time. The unseen grade uses the end-of-day vector. Served and candidate grades of one day are two reads, not one paired number.
- A deployment where the sweep is off writes an empty object with coverage 0 and grades nothing.

After deployment, check the new properties on a live sweep's events.
Check the first `model_role = 'served'` early grades the next day, and the mature grades as each head's horizon passes.
Until a model trained with thresholds is served, the events have no threshold properties and the served grades have null classification fields.
