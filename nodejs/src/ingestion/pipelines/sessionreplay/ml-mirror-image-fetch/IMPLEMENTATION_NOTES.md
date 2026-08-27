# Image fetcher implementation notes

The [README](./README.md) is the normative specification. This file records the implementation, assumptions, and rollout constraints.

## Implementation map

### URL collection and identity

The shared Rust URL policy performs admission, canonicalization, and global ref creation. It refuses private targets, credentials, userinfo, and known signed URLs.

The mirror emits versioned frontier jobs. Each job carries the original ref, current URL, remaining hops, timing, and amplification counters.

The mirror can read crawl history after its local URL cache and before Kafka. It suppresses URLs whose next fetch time is still in the future. A timeout or store error publishes every candidate. The fetch consumer repeats the read because a completion can race with the mirror.

Kafka uses the registrable domain as the frontier key. Token-bucket rate and burst settings use that key when enabled. Active-request, transient back-off, and circuit-breaker state also use that key. Policy caches and crawl delay use the full origin.

### Policy and network boundary

The fetcher evaluates `robots.txt`, TDMRep, response opt-outs, and HTTP cache metadata. Configuration misses are coalesced per origin and file.

The fetcher follows configuration redirects only inside the source registrable domain. It treats a cross-registrable-domain redirect as unreachable.

The shared streamed-request helper preserves repeated response field lines. Policy evaluation therefore sees every opt-out field in received order.

Production requests use Smokescreen. The Rust admission policy also refuses every IP literal, including a public IP literal.

Web Bot Auth uses the shared PostHog key directory. The directory response has a 60-second public cache lifetime.

### Scheduling and retries

Each registrable domain has an optional token bucket, an active-request limit, a transient-failure count, and a circuit breaker. Each origin has its own crawl delay and configuration-request state. Each runtime map contains at most 20,000 entries. The default disables the token bucket. The default allows 6 active requests. An explicit robots.txt crawl delay still spaces requests to its origin.

A registrable domain remains in memory while it is active, blocked, or has a pending request grant. An origin remains in memory while it has an active or scheduled request, a reserved image-request start, or an unelapsed crawl delay. A full map defers untracked work without network access.

The fetch pass deduplicates jobs by global canonical ref. It groups the remaining jobs by registrable domain and origin. Two indexed priority queues select work in logarithmic time. Each queue gets a capped proportional concurrency target. The scheduler selects the queue that is furthest below its target. It uses the waiting job count and insertion order as tie-breakers.

The queue tracks the remaining request slots from active and waiting jobs. It applies the configured registrable-domain and pod limits. When fewer than 48 slots remain, low-diversity mode can start. More than 50 waiting URL jobs must still be eligible for a diversity deferral. The pass processes 8 more jobs. It then republishes each eligible tail job to the frontier. The mode stays active for the rest of the pass. A durable optional marker limits this fast deferral to once per job. Previously deferred jobs proceed normally until the pass deadline.

The frontier consumer uses cooperative rebalancing. Its revoke path drains active work before it releases assigned partitions.

Each image-fetch worker creates two Kafka group members by default. A local joiner combines their batches before it starts a fetch pass. Group assignments do not overlap, so each ready member adds a different partition. The joiner processes available batches when its join window ends. A later group can run concurrently instead of spending its Kafka poll interval behind a full pass. Shared request limits still bound total network concurrency. The worker divides the existing Kafka prefetch memory budget across its group members. During a mixed-version rollout, pods with more group members can receive more partitions until the rollout finishes. `SESSION_RECORDING_ML_IMAGE_FETCH_TARGET_PARTITIONS_PER_BATCH` accepts targets from one to four for worker-count experiments.

Retry jobs use 1-minute, 10-minute, and 1-hour Kafka topics. The topics use broker append timestamps.

Each delay consumer waits once for the latest record in its batch. It then republishes the complete batch to the frontier.

The fetch consumer buffers republished jobs until the fetch pass ends. It groups them by destination topic and current registrable domain, then packs each group to the shared job-count and byte limits. Redirects and pass-deadline deferrals return to the frontier. Work with a positive required wait uses a delay topic. Kafka deliveries use the configured pending-publish limit. One failed delivery stops the batch from starting more records, which bounds partial-delivery amplification before the source offsets retry. A monotonic deadline stops new deliveries 200 seconds after the poll batch starts. The producer's 20-second message timeout and the crawl-history store's 50-second batch budget plus command timeout keep the worst-case finalization near 275 seconds, below Kafka's 300-second poll limit.

One source-domain record can redirect to several target registrable domains. Such a batch can publish more frontier records than it consumed. The lane keeps each target domain as a separate Kafka key instead of delaying a zero-wait redirect.

### Durable completion

DynamoDB stores URL outcomes and configuration entries. Reads use 100-item batches and writes use 25-item batches. Large configuration bodies use immutable generation-specific chunks that publish before their manifest.

The client retries unprocessed keys and items with bounded concurrency and time. An incomplete chunk generation is a logged cache miss that the next configuration fetch repairs. A malformed base item fails the Kafka batch.

For a successful fetch, the producer publishes the image before DynamoDB records completion. Kafka offsets commit only after both operations succeed.

Frontier records retain work until a terminal result. A pass deadline defers unfinished jobs instead of dropping them.

### Fetch-to-scrub transport

The fetch producer sends the encoded response body as the Kafka value. Headers carry the content type and ordered content codings.

The production fetch queue can hold one full 100-record batch at the response-size limit. The delay consumers publish sequentially to avoid queue-full replay loops.

The scrubber decodes supported codings in reverse order. It enforces the uncompressed limit during each decoding layer and verifies the image signature.

Inline images retain sharded storage and Parquet indexes. URL images use `scrubbed-images/url/<global-hash>` for deterministic direct lookup. Conditional creates keep the first scrubbed image written for each global ref.

URL-image S3 writes use the scrub worker concurrency bound. A full scrub batch cannot create an unbounded S3 request burst.

The ML data-preparation resolver reads URL images by global ref. It removes sibling ref attributes before rendering, including when an image is absent.

### Operations

Metrics cover terminal outcomes, requests, origin policy, registrable-domain request state, retries, amplification, system time, and DynamoDB failures. Mirror metrics separate fresh history, misses, errors, and read duration. Every metric label defined by this lane uses a fixed category.

Batch-diversity histograms record the top 1, 5, and 10 URL shares and the inverse Simpson effective count for origins and registrable domains. Fetch-pass histograms record immediately schedulable slots and their ratio to the pod request limit. These metrics use only fixed scope and top-count labels.

`ml_image_fetch_republished_total` keeps the `topic` label key for rolling compatibility. The only values emitted by the new code are `frontier` and `delay`.

Republish batch metrics use the fixed topic classes `frontier`, `retry_1m`, `retry_10m`, and `retry_1h`. They expose Kafka record count, registrable-domain key count, per-topic delivery time, and total republish flush time. They do not use a configured topic name or a domain as a label.

The Grafana dashboard uses these runtime metrics. Its frontier health panels exclude the delay topics so they do not double-count retry traffic.

The Helm deployment defines fetch, scrub, and three retry consumers. Fetch and retry synchronization remains manual until their dependencies exist.

The optional fetch dead-letter topic stores each rejected frontier record with its original key and value. It adds bounded headers for the reason, schema version class, source topic, partition, and offset. The value can contain an original URL, so this topic has the same sensitivity as the frontier. The consumer waits for every dead-letter acknowledgement before it can commit the source offset. It publishes with bounded concurrency and a 50-second batch budget after other batch work succeeds. A failed publish fails the source batch. A retry can duplicate records that reached the dead-letter topic before another dead-letter publish failed. Operators can identify those duplicates by source topic, partition, and offset. The lane has no automatic dead-letter replay.

## Failure-mode observability

The lane uses bounded labels for all signals. The dashboards group failures by a fixed operation, reason, outcome, stage, or destination.

| Failure mode                                                                                           | Primary signal                                                                                                                                                                                                                                                                  | Dashboard or alert                                                                                                                                                                                      | Response                                                                                                                                                            |
| ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The 40-second pass budget is too short.                                                                | `ml_image_fetch_republished_total{reason="pass_deadline"}` divided by completed URLs plus all republishes                                                                                                                                                                       | Fetch dashboard: **Pass deadline deferral rate**. Alert: `IngestionSessionReplayImageFetchPassDeadlineSaturated`.                                                                                       | Increase capacity first. Increase the pass budget only if active batch age keeps enough margin below Kafka's 300-second poll limit.                                 |
| A fetch batch approaches Kafka's 300-second poll limit.                                                | Active batch age exceeds 180 seconds. Completed batch duration shows the recent distribution.                                                                                                                                                                                   | Fetch dashboard: **Poll batch duration**. Alert: `IngestionSessionReplayImageFetchBatchNearPollLimit`.                                                                                                  | Check store latency and request scheduling. Scale the lane before changing the pass budget.                                                                         |
| The fetch lane cannot drain its frontier topic.                                                        | Frontier lag exceeds 1,000 records and stays flat or projects more than 10% growth in one hour.                                                                                                                                                                                 | Fetch dashboard: Kafka lag and drain time. Alert: `IngestionSessionReplayImageFetchNotDraining`.                                                                                                        | Check consumer members, pod capacity, request waits, and deadline deferrals.                                                                                        |
| DynamoDB is slow, or a DynamoDB or Kafka request fails.                                                | Crawl-history duration by operation and outcome, a store error, a republish failure, or a failed retry release. A durable consumer-loop error log covers a pod that exits before a metrics scrape.                                                                              | Fetch dashboard: **Store health and delivery failures**. Loki alert: `IngestionSessionReplayImageFetchConsumerLoopFailed`.                                                                              | Check the failed or slow operation. Do not discard or manually commit the affected offsets.                                                                         |
| Kafka republishing consumes a large part of the poll interval.                                         | Total republish flush duration and per-topic delivery time increase. Records and registrable-domain keys per topic show whether the cause is volume, redirect fan-out, or delivery latency. A finalization-deadline counter records batches that stop before all records start. | Fetch dashboard: **Republish messages and registrable domains per batch**, **Republish batch duration**, **Store health and delivery failures**, and **Poll batch duration**.                           | Check Kafka producer latency and target-domain fan-out. Keep the active batch below Kafka's poll limit.                                                             |
| The fetch lane is alive but the input is empty.                                                        | Polls increase, consumer members remain present, and batch utilization is zero.                                                                                                                                                                                                 | Fetch dashboard: lane liveness and poll batch utilization.                                                                                                                                              | Check the version 2 mirror producer and the input-topic production rate.                                                                                            |
| Poll batches contain few distinct origins or registrable domains, or the pod reaches request capacity. | Distinct counts, top 1, 5, and 10 URL shares, effective counts, immediately schedulable slots, scheduler waits, requests in flight, deadline deferrals, and `not_ready` republishes.                                                                                            | Fetch dashboard: batch diversity, request capacity, scheduler waits, origin policy, registrable-domain state, request outcomes, and republishes.                                                        | Increase batch size only when low diversity coincides with low request use, scoped scheduler wait, and sufficient Kafka poll margin. Scale pods for pod saturation. |
| A dominant origin leaves too little diversity to use pod request capacity.                             | Low-origin-diversity pass count, origins, canonical URL jobs, and request slots at mode entry, and `ml_image_fetch_republished_total{reason="low_origin_diversity",topic="frontier"}`.                                                                                          | Fetch dashboard: batch diversity, low-origin-diversity deferrals, request capacity, and Kafka lag.                                                                                                      | Tune the request-slot and tail thresholds only after comparing them with in-flight use and lag. The fixed progress allowance must remain positive.                  |
| A registrable domain repeatedly fails, or an origin refuses access.                                    | Request outcomes, bounded retry causes, registrable-domain block state, origin-policy decisions, and terminal refusal reasons change.                                                                                                                                           | Fetch dashboard: request outcomes, retry causes, policy and budget decisions, and refused URLs.                                                                                                         | Check the origin policy and response status. Do not override an opt-out signal.                                                                                     |
| Retry release cannot return work to the frontier.                                                      | `ml_image_fetch_retry_released_total{outcome="failed"}` and a durable consumer-loop error log.                                                                                                                                                                                  | Fetch dashboard: delivery failures. Loki alert: `IngestionSessionReplayImageFetchConsumerLoopFailed`.                                                                                                   | Check the frontier producer and Kafka connectivity.                                                                                                                 |
| Retry input is invalid.                                                                                | `ml_image_fetch_retry_released_total` increases with a `malformed` or `invalid_timestamp` outcome. Missing content is committed and dropped. An invalid timestamp leaves the offset uncommitted and writes a durable consumer-loop error log.                                   | Fetch dashboard: delivery failures. Alerts: `IngestionSessionReplayImageFetchRetryInputRejected` for missing content and `IngestionSessionReplayImageFetchConsumerLoopFailed` for an invalid timestamp. | Check the retry producer and the delay topic's `LogAppendTime` configuration.                                                                                       |
| The fetch consumer rejects frontier input.                                                             | `ml_image_fetch_consumer_dead_lettered_total` increases after Kafka acknowledges the original record. `ml_image_fetch_consumer_dropped_total` counts the rejected jobs.                                                                                                         | Fetch dashboard: quarantine activity and **URLs refused**. Alert: `IngestionSessionReplayImageFetchInputRejected` for a sustained rate.                                                                 | Check the mirror and fetch versions and the frontier record schema. Inspect the restricted dead-letter topic only when necessary.                                   |
| The fetch consumer cannot quarantine rejected input.                                                   | `ml_image_fetch_consumer_dead_letter_failed_total` increases and `ml_image_fetch_dead_letter_publish_failed` logs before the consumer fails the batch. The source offsets remain uncommitted.                                                                                   | Fetch dashboard: quarantine activity. Alerts: `IngestionSessionReplayImageFetchDeadLetterPublishFailed` and the durable-log `IngestionSessionReplayImageFetchConsumerLoopFailed`.                       | Check the dead-letter topic, producer connectivity, and message-size configuration.                                                                                 |
| A retry worker shuts down during a deliberate wait.                                                    | `ml_image_fetch_retry_released_total{outcome="abandoned"}` increases. The consumer does not commit that offset.                                                                                                                                                                 | Fetch dashboard only. This expected shutdown outcome does not alert.                                                                                                                                    | Check pod lifecycle only if the rate does not match a rollout or scale-down.                                                                                        |
| The scrub sidecar is saturated or unreachable.                                                         | Scrub waits increase by `busy`, `timeout`, or `transport`.                                                                                                                                                                                                                      | Scrub dashboard: scrub waits and sidecar pressure. Alert: `IngestionSessionReplayImageScrubSidecarUnreachable`.                                                                                         | Scale for `busy`. Check CPU for `timeout`. Check pod health for `transport`.                                                                                        |
| The scrub consumer rejects input.                                                                      | `ml_mirror_image_scrub_consumer_invalid_key_total` increases. The consumer commits and drops the record.                                                                                                                                                                        | Scrub dashboard: invalid-key events. Alert: `IngestionSessionReplayImageScrubInputRejected`.                                                                                                            | Check the fetch and scrub versions, the content-ref format, and the scrub topic.                                                                                    |
| One image blocks later offsets.                                                                        | Stuck-image events increase, batch retired ratio falls, or batch duration approaches 300 seconds.                                                                                                                                                                               | Scrub dashboard: batch progress, batch duration, and quarantine events.                                                                                                                                 | Find the image ref in logs. Check if dead-letter publication succeeds.                                                                                              |
| Scrub output cannot reach S3 or the dead-letter topic.                                                 | A write batch failure or dead-letter publication failure occurs. Durable error logs cover a pod that exits before a metrics scrape.                                                                                                                                             | Scrub dashboard: consumer delivery failures. Loki alerts: `IngestionSessionReplayImageScrubConsumerLoopFailed` and `IngestionSessionReplayImageScrubDeadLetterPublishFailed`.                           | Check bucket access, topic configuration, and maximum Kafka message size.                                                                                           |
| A dead-letter replay cannot recover an image.                                                          | The replay emits `image_scrub_replay_exhausted`. The process metric is also visible if a scrape catches the bounded replay run.                                                                                                                                                 | Scrub dashboard: quarantine events. Loki alert: `IngestionSessionReplayImageScrubReplayExhausted`.                                                                                                      | Fix or accept the permanent sidecar refusal before Kafka retention removes the parked bytes.                                                                        |
| A scrub batch approaches Kafka's 300-second poll limit.                                                | Active batch age exceeds 180 seconds. Completed batch duration shows the recent distribution.                                                                                                                                                                                   | Scrub dashboard: **Image and batch duration**. Alert: `IngestionSessionReplayImageScrubBatchNearPollLimit`.                                                                                             | Check the retired ratio, stuck images, waits, CPU, and memory.                                                                                                      |
| The scrub lane cannot drain.                                                                           | Scrub frontier lag exceeds 1,000 records and stays flat or projects more than 10% growth in one hour.                                                                                                                                                                           | Scrub dashboard: Kafka lag and drain time. Alert: `IngestionSessionReplayImageScrubNotDraining`.                                                                                                        | Check waits, head-of-line blocking, CPU, memory, and consumer restarts.                                                                                             |

The pass-budget alert is inactive in dry-run mode. Delay-topic lag has no alert because queued delay records are expected. Generic Kubernetes alerts cover pod crash loops and unavailable replicas.

## Assumptions

- Only the `src` attribute creates a remote-image ref. The collector does not create refs for `rr_src` or `poster`.
- A response can contain at most four content-coding layers. This bound limits decompression work while retaining common stacked encodings.
- The standard pass is shorter than the minimum image retry delay. Active back-off therefore follows requirement 7.13 without an in-memory second pass.
- Smokescreen is the authoritative production DNS and connection boundary. Local URL admission is an additional fail-closed check.
- The fetch deployment uses Smokescreen without proxy credentials. The lane does not send `Proxy-Authorization`.
- The Web Bot Auth private key and Kubernetes secret remain operator-managed. No private key material belongs in these repositories.
- The DynamoDB table and its workload identity permissions exist before the fetch deployment becomes active.
- The mirror workload has DynamoDB read permission before deployment.
- The shared ML bucket grants the data-preparation workload read access to the deterministic URL-image prefix.
- Retry topics use the `ai_research_session_replay_` naming convention.
- Replacement infrastructure provisions the required topics before consumers start. No deployed producer or consumer uses the deprecated names.
- Deprecated topics remain protected and unused. Their cleanup is not required for this rollout.
- Current public documentation already describes the collector-side image limits. No separate documentation repository change is required.
- A cross-registrable-domain configuration redirect fails closed. This rule prevents a source Kafka partition from creating request state for another partition's registrable domain.
- Low-origin-diversity thresholds count canonical URL jobs, not Kafka records. One Kafka record can contain from 1 to 1,000 jobs, so record count does not measure the remaining request work.
- The 8-origin, 50-job, and 8-job progress defaults are initial operational values. Bounded metrics expose how often they defer work without adding origin or registrable-domain labels.
- Deduplication uses the global canonical ref. Redirect targets keep separate original refs because their terminal results must complete the replay URLs that created those refs.
- An older consumer ignores and can remove the optional diversity-deferral marker when it republishes a job during a rolling deployment. This can add one extra deferral during the deployment window, but it does not reject or lose the job.

## Delta from the original requirements

The implementation has four product-behavior or interface deltas from the original requirements.

| Original requirement                                                          | Final implementation                                                                   | Reason and effect                                                                                                                                                                                                                             |
| ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Accept any number of supported content-coding layers.                         | Accept at most four layers.                                                            | This bound limits decompression work. A response with more than four layers is refused. Requirements 14.1 and 17.6 now state this bound.                                                                                                      |
| Export top-N registrable and provider domains and exact HTTP response values. | Export no registrable-domain or provider-domain labels and group HTTP status by class. | The metrics system does not support high-cardinality labels. Fixed categories keep the number of time series bounded. Per-registrable-domain request share is not available in metrics. Requirements 11.2 and 11.6 now state this rule.       |
| Apply one crawl delay across a registrable domain.                            | Apply each crawl delay only to the origin that published it.                           | robots.txt answers for one origin. Sibling origins still share any enabled rate and burst, plus active-request, transient back-off, and circuit-breaker controls. Requirements 5.11, 5.12, 7.10, and 7.11 state the split.                    |
| Follow a configuration redirect to any authority without Kafka republishing.  | Follow it only inside the source registrable domain.                                   | Cross-registrable-domain redirects could create a second pod-local budget outside the target Kafka owner. The lane treats the source configuration as unreachable and does not request the target. Requirements 3.5 and 5.4 state this bound. |

The implementation also has these rollout and repository-state deltas. They do not change steady-state fetch behavior.

- The 40-second pass and its 50-second worst-case wall time are shorter than the first retry delay. Therefore, retries use the durable delay topic and do not use an in-memory second pass.
- Fetch and retry ApplicationSet synchronization stays manual until the cross-repository dependencies are active.
- The base charts change keeps `SESSION_RECORDING_ML_IMAGE_FETCH_DRY_RUN` set to `true` and `SESSION_RECORDING_ML_URL_PRODUCER_ENABLED` set to `false`.
- The first activation charts change clears fetch dry-run only after every consumer and infrastructure dependency is active.
- The second activation charts change enables the version 2 mirror producer after active fetching is verified.
- Web Bot Auth private keys and the Kubernetes secret stay outside source control. An operator must create them before activation.
- The DynamoDB table and workload identity permissions were already present on the current infrastructure `main` branch. This work does not create a duplicate table or duplicate permissions.
- The required public documentation was already present on the current `posthog.com` `master` branch. This work does not create an empty documentation pull request.

## Deployment order

The Node.js image with grouped, bounded republish delivery must be active before the chart raises the poll batch to 50 records and the request budget to 40 seconds. The older per-URL publisher can spend too much of Kafka's poll interval finalizing the larger batch.

1. Apply the Kafka topic sizes and broker timestamp settings from `posthog-cloud-infra`, including the image-fetch dead-letter topic.
2. Apply the DynamoDB table, workload permissions, Smokescreen, and required secrets.
3. Deploy the scrubber changes and the ML data-preparation resolver.
4. Deploy the fetch and retry workloads with automatic synchronization disabled. Keep fetch dry-run enabled and the version 2 mirror producer disabled.
5. Start each retry tier, then start the fetch workload and verify policy, refusal, origin-state, and registrable-domain-state metrics.
6. Apply the first activation charts change to enable image publishing, then verify fetch processing and downstream delivery.
7. Apply the second activation charts change to enable the version 2 mirror producer.
8. Enable automatic synchronization after the first production verification succeeds.

Do not activate a delay consumer before its topic uses `LogAppendTime`. Producer timestamps do not provide the required delay guarantee.
