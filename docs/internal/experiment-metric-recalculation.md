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

The workflow does not configure activity heartbeats.
Temporal requires heartbeats and a heartbeat timeout to deliver workflow cancellation to a running activity, so supersession does not promptly interrupt the calculation.
Prompt cancellation would require heartbeat delivery plus cooperative cancellation through precomputation and the query runner, with cleanup for any active ClickHouse query.
Result-write protection must remain independent of cancellation delivery.

See the [workflow architecture](../../products/experiments/backend/temporal/ARCHITECTURE.md) and [Temporal's cancellation contract](https://github.com/temporalio/sdk-python#heartbeating-and-cancellation).
