# Batch workflow audience resolution

How a batch-triggered workflow run resolves its audience, and the knobs that bound it.

## The resolver

Triggering a batch workflow creates one cyclotron job on `HOGFLOW_BATCH_RESOLVE_QUEUE`, processed by the `cdp-cyclotron-worker-batch-resolve` consumer. Each dequeue fetches one audience page from Django's internal endpoints (`user_blast_radius_persons` for person audiences, `account_audience` for account audiences), enqueues that page's runs, and reschedules itself with the next cursor until the audience is exhausted or truncated by `maxAudienceSize`. The terminal status (`completed`/`failed`) is PUT back to Django on a final dequeue, and the resolver only acks after that write succeeds.

## Audience fetch timeout

The page fetch runs a ClickHouse query, so it does not fit the generic 3s `EXTERNAL_REQUEST_TIMEOUT_MS` inter-service budget:

- `CDP_HOG_FLOW_BATCH_AUDIENCE_FETCH_TIMEOUT_MS` (default `30000`) — client-side budget in milliseconds for each audience fetch (blast-radius count, persons page, account page).

A fetch that exceeds the budget aborts, retries up to `MAX_RESOLVER_ATTEMPTS` times with backoff, and then the run is marked failed with `Batch resolver failed: Audience fetch failed permanently…` on the workflow's log stream. Keep the budget under the HogQL default `max_execution_time` (60s): above it, the client only waits longer for a query ClickHouse will kill anyway. Note the client abort does not cancel the ClickHouse query — a query slower than the budget keeps running server-side until the HogQL cap, so a too-small budget wastes a full query execution per attempt.

## Lock heartbeats and batch size

A near-budget fetch holds one job for ~30s, the same magnitude as the janitor's stall threshold (`CYCLOTRON_NODE_JANITOR_STALL_TIMEOUT_MS`, default 30s). Two things keep the janitor from reclaiming a healthy job:

- The consumer heartbeats the held job every 10s while it processes.
- It dequeues one job at a time (`batchMaxSize: 1`). Pages are processed serially, so a bigger batch adds no throughput — it only leaves queued peers un-heartbeated behind a slow fetch.

## Observing

- Fetch durations: `instrumented_function_duration_seconds` for `cdpBatchResolve.getBlastRadiusPersons` and `cdpBatchResolve.getAccountAudiencePage`. Watch the p99 against the budget before tuning either.
- Failures: `cdp_batch_hog_flow_resolver_pages_processed{outcome="fetch_failure"}`, and the `Batch resolver failed:` entry on the workflow's **Logs** tab (`log_source_id` = the batch job id).
