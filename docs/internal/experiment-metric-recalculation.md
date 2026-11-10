# Experiment metric recalculation cancellation

Experiment recalculations share result rows keyed by `(experiment, metric_uuid, query_to)`.
Stopped experiments reuse their fixed end date, so an abandoned run and its replacement can write the same row.

Result persistence locks the experiment and then the recalculation row in one transaction.
The status check and result upsert share that transaction, so a terminal transition either follows the old write or prevents it.
Missing, completed, and failed recalculations cannot write results.
The lock order matches `request_recalculation` and avoids a deadlock between supersession and the experiment foreign-key check on a new result.
ClickHouse queries and statistics run outside these locks.

The activity shields its synchronous calculation because canceling an asyncio task cannot stop a running worker thread.
After local activity cancellation, it waits for the calculation with a cleanup deadline of `METRIC_CALC_ACTIVITY_TIMEOUT_SECONDS` from the first cancellation.
Repeated cancellation does not restart or interrupt that wait.
The activity propagates the original cancellation even if the calculation fails during cleanup.

This cleanup preserves the worker's activity slot while it waits; it does not stop the query or immediately release its memory.
The deadline bounds cleanup, not the underlying thread's lifetime.
Precomputation, executor queuing, statistics, and database waits can extend beyond the final ClickHouse query's execution limit.
A calculation can therefore continue after the cleanup deadline expires.

Temporal delivers a workflow cancellation to a running activity only in a heartbeat response.
The calc activity heartbeats every `METRIC_CALC_HEARTBEAT_TIMEOUT_SECONDS / 4` while the calculation thread runs, and the workflow sets that heartbeat timeout on the call.
A workflow cancellation, or a timeout the server enforces, therefore reaches the activity and starts the cleanup above, which kills the active ClickHouse query.
Precomputation and the query runner do not cancel cooperatively, so the thread can still run past the kill.
Result-write protection must remain independent of cancellation delivery.

See the [workflow architecture](../../products/experiments/backend/temporal/ARCHITECTURE.md) and [Temporal's cancellation contract](https://github.com/temporalio/sdk-python#heartbeating-and-cancellation).

## Superseded timeseries backfills

A request with the same metric and calculation key reuses the active backfill. A different key cancels the old request and starts a replacement. Each daily write locks the experiment and checks the request status in the same transaction, preventing a superseded worker from overwriting the replacement's days. Queries run outside the transaction.

The request stores the metric's current definition and key, and ignores a definition or key in the request body. Until backfills consume a frozen calculation config, each day's runner must give the request's key, in the key version of that key, before executing. Settings drift cancels the request instead of storing a result under settings it did not use.

## Settings changes and stored results

The `experiment-calculation-key-v2` flag turns on calculation key version 2 for a team.
Version 2 hashes every analytical setting, including statistics, CUPED, test account filters and the timezone, so calculation reuse requires results from the current settings.
Version 1 omits those settings, so a result stored under it has unknown settings once the team uses version 2.

An ended experiment keeps its compatible stored result when project settings change.
Opening its results page does not request a replacement.
The page marks results from earlier settings or unrecorded settings and offers an explicit recalculation.
Such results stay visible and are never relabeled as current.
That recalculation updates the latest results only; time series points keep their stored values until a timeseries backfill recalculates them.
When the experiment is over the recalculation age limit, the latest response sets `exceeds_recalculation_age_limit`, and the page explains that the stored results stay as they are instead of offering the recalculation.

A failed recalculation never replaces a completed result row.
The row keeps its result and fingerprint, and the run records the failure in `metric_errors` and counts the metric as failed.
The page shows the failure, as it does for a metric without a stored result.
A failed daily calculation leaves a completed row under another fingerprint in place, and replaces a completed point under its own key, so the chart shows the latest attempt.

The API reports this provenance as `configuration_status` on each recalculation result and as `configuration_by_day` on the timeseries results: `current`, `previous` or `unknown`.
Under version 1, every result under the version 1 key reports `current`.

Under version 2, the query runner adds the calculation key to its response-cache payload, so dashboard widgets miss the cache for the same settings changes as the experiment page.
The first request for an affected cached response is therefore slower after a team turns on the flag.
