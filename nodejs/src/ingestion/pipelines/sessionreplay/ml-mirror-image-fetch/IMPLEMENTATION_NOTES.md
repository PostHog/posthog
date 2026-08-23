# Image fetcher implementation notes

The [README](./README.md) is the normative specification. This file records the implementation, assumptions, and rollout constraints.

## Implementation map

### URL collection and identity

The shared Rust URL policy performs admission, canonicalization, and global ref creation. It refuses private targets, credentials, userinfo, and known signed URLs.

The mirror emits versioned frontier jobs. Each job carries the original ref, current URL, remaining hops, timing, and amplification counters.

Kafka uses the registrable domain as the frontier key. Runtime limits and policy caches use the full origin.

### Policy and network boundary

The fetcher evaluates `robots.txt`, TDMRep, response opt-outs, and HTTP cache metadata. Configuration misses are coalesced per origin and file.

The shared streamed-request helper preserves repeated response field lines. Policy evaluation therefore sees every opt-out field in received order.

Production requests use Smokescreen. The Rust admission policy also refuses every IP literal, including a public IP literal.

Web Bot Auth uses the shared PostHog key directory. The directory response has a 60-second public cache lifetime.

### Scheduling and retries

Each origin has a token bucket, concurrency limit, crawl delay, transient-failure count, and circuit breaker. The runtime map contains at most 20,000 origins.

An origin remains in memory while it is active, blocked, reserved, or running a configuration request. A full map defers an untracked origin without network access.

The frontier consumer uses cooperative rebalancing. Its revoke path drains active work before it releases assigned partitions.

Retry jobs use 1-minute, 10-minute, and 1-hour Kafka topics. The topics use broker append timestamps.

Each delay consumer waits once for the latest record in its batch. It then republishes the complete batch to the frontier.

### Durable completion

DynamoDB stores URL outcomes and configuration entries. Reads use 100-item batches and writes use 25-item batches. Large configuration bodies use immutable generation-specific chunks that publish before their manifest.

The client retries unprocessed keys and items with bounded concurrency and time. An incomplete chunk generation is a logged cache miss that the next configuration fetch repairs. A malformed base item fails the Kafka batch.

For a successful fetch, the producer publishes the image before DynamoDB records completion. Kafka offsets commit only after both operations succeed.

Frontier records retain work until a terminal result. A pass deadline defers unfinished jobs instead of dropping them.

### Fetch-to-scrub transport

The fetch producer sends the encoded response body as the Kafka value. Headers carry the content type and ordered content codings.

The production fetch queue can hold one full 100-record batch at the response-size limit. The delay consumers publish sequentially to avoid queue-full replay loops.

The scrubber decodes supported codings in reverse order. It enforces the uncompressed limit during each decoding layer and verifies the image signature.

Inline images retain sharded storage and Parquet indexes. URL images use `scrubbed-images/url/<global-hash>` for deterministic direct lookup. Conditional writes use the source Kafka partition and offset to prevent an old partition owner from replacing newer bytes.

URL-image S3 writes use the scrub worker concurrency bound. A full scrub batch cannot create an unbounded S3 request burst.

The ML data-preparation resolver reads URL images by global ref. It removes sibling ref attributes before rendering, including when an image is absent.

### Operations

Metrics cover terminal outcomes, requests, origin state, retries, amplification, system time, DynamoDB failures, and bounded heavy hitters.

The Grafana dashboard uses these runtime metrics. Its frontier health panels exclude the delay topics so they do not double-count retry traffic.

The Helm deployment defines fetch, scrub, and three retry consumers. Fetch and retry synchronization remains manual until their dependencies exist.

## Failure-mode observability

The lane uses bounded labels for all failure signals. The dashboards group failures by a fixed operation, reason, outcome, stage, or topic.

| Failure mode | Primary signal | Dashboard or alert | Response |
| --- | --- | --- | --- |
| The 20-second pass budget is too short. | `ml_image_fetch_republished_total{reason="pass_deadline"}` divided by completed URLs plus all republishes | Fetch dashboard: **Pass deadline deferral rate**. Alert: `IngestionSessionReplayImageFetchPassDeadlineSaturated`. | Increase capacity first. Increase the pass budget only if active batch age keeps enough margin below Kafka's 300-second poll limit. |
| A fetch batch approaches Kafka's 300-second poll limit. | Active batch age exceeds 180 seconds. Completed batch duration shows the recent distribution. | Fetch dashboard: **Poll batch duration**. Alert: `IngestionSessionReplayImageFetchBatchNearPollLimit`. | Check store latency and request scheduling. Scale the lane before changing the pass budget. |
| The fetch lane cannot drain its frontier topic. | Frontier lag exceeds 1,000 records and stays flat or projects more than 10% growth in one hour. | Fetch dashboard: Kafka lag and drain time. Alert: `IngestionSessionReplayImageFetchNotDraining`. | Check consumer members, pod capacity, request waits, and deadline deferrals. |
| DynamoDB is slow, or a DynamoDB or Kafka request fails. | Crawl-history duration by operation and outcome, a store error, a republish failure, or a failed retry release. A durable consumer-loop error log covers a pod that exits before a metrics scrape. | Fetch dashboard: **Store health and delivery failures**. Loki alert: `IngestionSessionReplayImageFetchConsumerLoopFailed`. | Check the failed or slow operation. Do not discard or manually commit the affected offsets. |
| The fetch lane is alive but the input is empty. | Polls increase, consumer members remain present, and batch utilization is zero. | Fetch dashboard: lane liveness and poll batch utilization. | Check the version 2 mirror producer and the input-topic production rate. |
| One origin or the pod reaches request capacity. | Scheduler wait time by `origin_budget` or `request_capacity`, requests in flight, deadline deferrals, and `not_ready` republishes increase. | Fetch dashboard: request capacity, scheduler waits, origin state, request outcomes, and republishes. | Scale pods for pod saturation. Check origin limits before changing per-origin controls. |
| An origin repeatedly fails or refuses access. | Request outcomes, origin block state, and terminal refusal reasons change. | Fetch dashboard: request outcomes, origin decisions, and refused URLs. | Check the origin policy and response status. Do not override an opt-out signal. |
| Retry release cannot return work to the frontier. | `ml_image_fetch_retry_released_total{outcome="failed"}` and a durable consumer-loop error log. | Fetch dashboard: delivery failures. Loki alert: `IngestionSessionReplayImageFetchConsumerLoopFailed`. | Check the frontier producer and Kafka connectivity. |
| Retry input is invalid. | `ml_image_fetch_retry_released_total` increases with a `malformed` or `invalid_timestamp` outcome. Missing content is committed and dropped. An invalid timestamp leaves the offset uncommitted and writes a durable consumer-loop error log. | Fetch dashboard: delivery failures. Alerts: `IngestionSessionReplayImageFetchRetryInputRejected` for missing content and `IngestionSessionReplayImageFetchConsumerLoopFailed` for an invalid timestamp. | Check the retry producer and the delay topic's `LogAppendTime` configuration. |
| The fetch consumer rejects frontier input. | `ml_image_fetch_consumer_dropped_total` increases by a bounded reason. The consumer commits and drops those jobs. | Fetch dashboard: **URLs refused**. Alert: `IngestionSessionReplayImageFetchInputRejected`. | Check the mirror and fetch versions and the frontier record schema. |
| A retry worker shuts down during a deliberate wait. | `ml_image_fetch_retry_released_total{outcome="abandoned"}` increases. The consumer does not commit that offset. | Fetch dashboard only. This expected shutdown outcome does not alert. | Check pod lifecycle only if the rate does not match a rollout or scale-down. |
| The scrub sidecar is saturated or unreachable. | Scrub waits increase by `busy`, `timeout`, or `transport`. | Scrub dashboard: scrub waits and sidecar pressure. Alert: `IngestionSessionReplayImageScrubSidecarUnreachable`. | Scale for `busy`. Check CPU for `timeout`. Check pod health for `transport`. |
| The scrub consumer rejects input. | `ml_mirror_image_scrub_consumer_invalid_key_total` increases. The consumer commits and drops the record. | Scrub dashboard: invalid-key events. Alert: `IngestionSessionReplayImageScrubInputRejected`. | Check the fetch and scrub versions, the content-ref format, and the scrub topic. |
| One image blocks later offsets. | Stuck-image events increase, batch retired ratio falls, or batch duration approaches 300 seconds. | Scrub dashboard: batch progress, batch duration, and quarantine events. | Find the image ref in logs. Check if dead-letter publication succeeds. |
| Scrub output cannot reach S3 or the dead-letter topic. | A write batch failure or dead-letter publication failure occurs. Durable error logs cover a pod that exits before a metrics scrape. | Scrub dashboard: consumer delivery failures. Loki alerts: `IngestionSessionReplayImageScrubConsumerLoopFailed` and `IngestionSessionReplayImageScrubDeadLetterPublishFailed`. | Check bucket access, topic configuration, and maximum Kafka message size. |
| A dead-letter replay cannot recover an image. | The replay emits `image_scrub_replay_exhausted`. The process metric is also visible if a scrape catches the bounded replay run. | Scrub dashboard: quarantine events. Loki alert: `IngestionSessionReplayImageScrubReplayExhausted`. | Fix or accept the permanent sidecar refusal before Kafka retention removes the parked bytes. |
| A scrub batch approaches Kafka's 300-second poll limit. | Active batch age exceeds 180 seconds. Completed batch duration shows the recent distribution. | Scrub dashboard: **Image and batch duration**. Alert: `IngestionSessionReplayImageScrubBatchNearPollLimit`. | Check the retired ratio, stuck images, waits, CPU, and memory. |
| The scrub lane cannot drain. | Scrub frontier lag exceeds 1,000 records and stays flat or projects more than 10% growth in one hour. | Scrub dashboard: Kafka lag and drain time. Alert: `IngestionSessionReplayImageScrubNotDraining`. | Check waits, head-of-line blocking, CPU, memory, and consumer restarts. |

The pass-budget alert is inactive in dry-run mode. Delay-topic lag has no alert because queued delay records are expected. Generic Kubernetes alerts cover pod crash loops and unavailable replicas.

## Assumptions

- Only the `src` attribute creates a remote-image ref. The collector does not create refs for `rr_src` or `poster`.
- A response can contain at most four content-coding layers. This bound limits decompression work while retaining common stacked encodings.
- The standard pass is shorter than the minimum image retry delay. Active back-off therefore follows requirement 7.13 without an in-memory second pass.
- Smokescreen is the authoritative production DNS and connection boundary. Local URL admission is an additional fail-closed check.
- The fetch deployment uses Smokescreen without proxy credentials. The lane does not send `Proxy-Authorization`.
- The Web Bot Auth private key and Kubernetes secret remain operator-managed. No private key material belongs in these repositories.
- The DynamoDB table and its workload identity permissions exist before the fetch deployment becomes active.
- The shared ML bucket grants the data-preparation workload read access to the deterministic URL-image prefix.
- The image-scrub topic partition count remains fixed while deterministic URL-image objects exist. The source-offset write fence refuses a ref that moves between partitions.
- Retry topics use the replay cluster's existing `session_replay_` naming convention.
- Current public documentation already describes the collector-side image limits. No separate documentation repository change is required.

## Delta from the original requirements

The implementation has three product-behavior or interface deltas from the original README.

| Original requirement                                                                 | Final implementation                                      | Reason and effect                                                                                                                                                   |
| ------------------------------------------------------------------------------------ | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Accept any number of supported content-coding layers.                                | Accept at most four layers.                               | This bound limits decompression work. A response with more than four layers is refused. Requirements 14.1 and 17.6 now state this bound.                            |
| Remove the `cb`, `nocache`, `rnd`, and scoped Meta query fields from the global ref. | Keep every query field in the global ref.                 | An arbitrary origin can use these names to select different bytes. Keeping them prevents cross-tenant object-key collisions. Requirement 13.3 now states this rule. |
| Use delay topic names with the `ai_research_session_replay_` prefix.                 | Use the existing replay-cluster `session_replay_` prefix. | This keeps the topics consistent with the deployed replay naming convention. Requirement 16.2 now lists the deployed names.                                         |

The implementation also has these rollout and repository-state deltas. They do not change steady-state fetch behavior.

- The 20-second pass is shorter than the first retry delay. Therefore, retries use the durable delay topic and do not use an in-memory second pass.
- Fetch and retry ApplicationSet synchronization stays manual until the cross-repository dependencies are active.
- The base charts change keeps `SESSION_RECORDING_ML_IMAGE_FETCH_DRY_RUN` set to `true` and `SESSION_RECORDING_ML_URL_PRODUCER_ENABLED` set to `false`.
- The first activation charts change clears fetch dry-run only after every consumer and infrastructure dependency is active.
- The second activation charts change enables the version 2 mirror producer after active fetching is verified.
- Web Bot Auth private keys and the Kubernetes secret stay outside source control. An operator must create them before activation.
- The DynamoDB table and workload identity permissions were already present on the current infrastructure `main` branch. This work does not create a duplicate table or duplicate permissions.
- The required public documentation was already present on the current `posthog.com` `master` branch. This work does not create an empty documentation pull request.

## Deployment order

1. Apply the Kafka topic sizes and broker timestamp settings from `posthog-cloud-infra`.
2. Apply the DynamoDB table, workload permissions, Smokescreen, and required secrets.
3. Deploy the scrubber changes and the ML data-preparation resolver.
4. Deploy the fetch and retry workloads with automatic synchronization disabled. Keep fetch dry-run enabled and the version 2 mirror producer disabled.
5. Start each retry tier, then start the fetch workload and verify policy, refusal, and origin-state metrics.
6. Apply the first activation charts change to enable image publishing, then verify fetch processing and downstream delivery.
7. Apply the second activation charts change to enable the version 2 mirror producer.
8. Enable automatic synchronization after the first production verification succeeds.

Do not activate a delay consumer before its topic uses `LogAppendTime`. Producer timestamps do not provide the required delay guarantee.
