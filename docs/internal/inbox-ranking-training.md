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
