# Local logs alert comparison

`products.logs.backend.alert_comparison.compare_logs_alert_cohort` compares one supplied cohort with the logs adapter in `alert_evaluation.py`.
It does not load configurations, discover due alerts, query ClickHouse, send notifications, or save results.
The adapter is not registered in the insight dispatcher or connected to the production scheduler.

Pass a fully loaded `_AlertCohort`, its `_CohortQueryResult`, and the captured `now` and ingestion `checkpoint`.
Use the same configuration, state, bucket counts, checkpoint, and clock on retries.
The cohort window must match that configuration and checkpoint.
The function copies configurations and bucket lists before evaluation and rejects missing per-alert evidence rather than issuing a query.
Keep each input bounded by `MAX_ALERT_COHORT_SIZE`; do not flatten multiple query grids into one cohort.
Start with synthetic inputs in `products/logs/backend/test/test_alert_evaluation.py`:

```sh
hogli test products/logs/backend/test/test_alert_evaluation.py
```

The adapter runs the existing shared absolute threshold comparator once per rolling count.
Its source-specific result keeps each shared `AlertEvaluationResult` and all newest-first breach flags, including implicit zeros.
The existing logs state-machine wrapper applies N-of-M, cooldown, snooze, and error handling to those flags.
Neither the source query layer nor its filtering, batching, byte limits, projection selection, or cluster routing changes.

Comparison fields report counts, bucket evidence, classified error behavior, proposed lifecycle, proposed notifications, and window identity separately.
Notifications are pre-dispatch proposals: quiet hours, destination delivery, and delivery-failure rollback are not simulated.
Both paths intentionally use the existing lifecycle state machine; this checks adapter input parity, not an independent implementation of that machine.
Legacy evaluation diagnostics are disabled only for the comparison, so it does not add live alert metrics or exception reports.

Counts use identical supplied evidence, not independently executed queries.
The legacy call retains the production cohort path's `checkpoint=None`.
With a fresh checkpoint behind `next_check_at`, the actual query window is clamped but the legacy reported window is not.
`windows_match` exposes that existing discrepancy even when the counts and outcomes match.
This is not evidence of end-to-end live-query parity.

Absent checkpoints and checkpoints more than five minutes behind the scheduled check retain the existing scheduled-time fallback.
They do not produce an inconclusive result in either logs path.
A requirement to suppress evaluation on missing or stale data would therefore disagree with this behavior and needs a separate decision.
No freshness policy, scheduler, or notification behavior changes here.
