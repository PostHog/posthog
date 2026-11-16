# Batch workflow audience resolution

How a batch-triggered workflow run resolves its audience, and the knobs that bound it.

## The resolver

Triggering a batch workflow creates one cyclotron job on `HOGFLOW_BATCH_RESOLVE_QUEUE`, processed by the `cdp-cyclotron-worker-batch-resolve` consumer. Each dequeue fetches one audience page from Django's internal endpoints (`user_blast_radius_persons` for person audiences, `account_audience` for account audiences), enqueues that page's runs, and reschedules itself with the next cursor until the audience is exhausted or truncated by `maxAudienceSize`. The terminal status (`completed`/`failed`) is PUT back to Django on a final dequeue, and the resolver only acks after that write succeeds.

## Audience fetch timeout

The page fetch runs a ClickHouse query, so it does not fit the generic 3s `EXTERNAL_REQUEST_TIMEOUT_MS` inter-service budget:

- `CDP_HOG_FLOW_BATCH_AUDIENCE_FETCH_TIMEOUT_MS` (default `30000`) — client-side budget in milliseconds for each audience fetch (blast-radius count, persons page, account page).

A fetch that exceeds the budget aborts, retries up to `MAX_RESOLVER_ATTEMPTS` times with backoff, and then the run is marked failed on the workflow's log stream.
A timeout gets its own terminal reason, `Batch resolver failed: Audience query timed out…`, which names the budget and the attempt count.
Any other fetch failure keeps the generic `Batch resolver failed: Audience fetch failed permanently…`, so search for both texts when you triage a failed run.
Keep the budget under the HogQL default `max_execution_time` (60s): above it, the client only waits longer for a query ClickHouse will kill anyway. Note the client abort does not cancel the ClickHouse query — a query slower than the budget keeps running server-side until the HogQL cap, so a too-small budget wastes a full query execution per attempt.

## Lock heartbeats and batch size

A near-budget fetch holds one job for ~30s, the same magnitude as the janitor's stall threshold (`CYCLOTRON_NODE_JANITOR_STALL_TIMEOUT_MS`, default 30s). Two things keep the janitor from reclaiming a healthy job:

- The consumer heartbeats the held job every 10s while it processes.
- It dequeues one job at a time (`batchMaxSize: 1`). Pages are processed serially, so a bigger batch adds no throughput — it only leaves queued peers un-heartbeated behind a slow fetch.

Lease heartbeats update the job's database lock; they do not refresh the worker's poll health check.
The worker waits for page processing to finish before polling again.
Its `heartbeatTimeoutMs` adds 30 seconds to the audience fetch budget for processing and monitoring flushes.
The default health timeout is 60 seconds.
This keeps an allowed slow fetch from reporting the worker as unhealthy while its lease remains valid.

## Observing

- Fetch durations: `instrumented_function_duration_seconds` for `cdpBatchResolve.getBlastRadiusPersons` and `cdpBatchResolve.getAccountAudiencePage`. Read the bucket counts rather than a quantile before tuning either. The finite bucket edges are 0.025, 0.1, 0.4, 1.6, 6.4, 25.6 and 102.4 seconds, so a quantile between two edges reports the share of slow fetches and not how long they took. `CdpBatchAudienceFetchSlow` counts fetches slower than 25.6s, the edge closest to the budget, and fires before any fetch aborts. That alert reads the persons function only. A slow account page therefore gets no warning before it starts to time out, so watch its bucket counts by hand or widen the alert.
- Timeouts: `cdp_batch_hog_flow_audience_fetch_timeout{endpoint}` counts each fetch that used its full budget and aborted. A timeout raises `AudienceFetchTimeoutError`, which is a separate type from a transport failure, so the retry logs and the customer-visible failure reason name the timeout. `CdpBatchAudienceFetchTimingOut` alerts on a sustained rate. Both alerts live in [PostHog/charts `alerts/specs/cdp.yaml`](https://github.com/PostHog/charts/blob/main/alerts/specs/cdp.yaml).
- Failures: `cdp_batch_hog_flow_resolver_pages_processed{outcome="fetch_failure"}`, and a `Batch resolver failed: <reason>` row in ClickHouse `log_entries` with `log_source = 'hog_flow'` and `log_source_id` = the **batch job id** (not the workflow id).
- Failure reasons: `cdp_batch_hog_flow_resolver_jobs{outcome="failed", reason}` names why a run ended. The reasons are `quota_limited`, `missing_entity`, `cohort_timeout`, `realtime_cohort_unavailable`, `audience_snapshot_timeout`, `audience_query_failed`, `fetch_failure`, `terminal_write_failure` and `invalid_state`. `quota_limited` means a billing limit refused the run, which is customer configuration and not a platform fault, so `CdpBatchRunsFailing` excludes it. A job written before this label existed reports an empty reason.

## Where the customer reads the failure reason

The resolver keys its failure, audience-truncation, and cancel logs by batch job id. `BatchRunLog` reads that same key, so each run on the Invocations tab shows its own entries above its invocations, including a run that enrolled nobody. Write every reason for a person, not for an engineer: say what happened, say that nobody was enrolled when that is true, and give the next action. The workflow's Logs panel still queries by workflow id and redirects to Invocations, so these entries do not appear there.
