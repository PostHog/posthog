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

## Settings changes and stored results

An ended experiment keeps its compatible stored result when project settings change. Opening its results page does not request a replacement. The page identifies results from earlier settings and offers explicit recalculation. Legacy results whose full settings were never recorded remain visible with unknown provenance; they are not relabeled as current.

Calculation reuse requires the current calculation key, including statistics, CUPED, test account filters and timezone. Display-key and legacy matches only preserve history. The query runner includes the calculation key in its response-cache payload so dashboard widgets invalidate the same settings as the experiment page.

## Superseded timeseries backfills

A request with the same metric and calculation key reuses the active backfill. A different key cancels the old request and starts a replacement. Each daily write locks the experiment and checks the request status in the same transaction, preventing a superseded worker from overwriting the replacement's days. Queries run outside the transaction.

Until backfills consume a frozen calculation config, each day's runner must match the request's calculation key before executing. Settings drift cancels the request instead of storing a result under settings it did not use.
