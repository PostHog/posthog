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
