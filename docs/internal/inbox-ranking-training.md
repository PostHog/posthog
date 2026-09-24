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
