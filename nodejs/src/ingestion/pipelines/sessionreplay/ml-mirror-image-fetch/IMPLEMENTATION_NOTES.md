# Image fetcher implementation notes

The [README](./README.md) is the normative specification. This file lists changes that the current implementation needs to satisfy that specification.

## Global URL refs

The current URL ref has the form `imageurl:<pseudo-team>:<hash>`. The hash uses a key derived for one team. The crawl-history key also contains the team pseudonym.

Change the URL collector, Kafka record parser, crawl-history key, image scrubber, S3 storage, and data-preparation lookup to use the global URL ref from requirement 13.5. Inline image refs can remain team-specific.

Derive one URL HMAC key from the existing ML pseudonymization secret without a team input. Pin the derivation from requirement 13.5 and the resulting test vectors in the shared Rust and Node fixtures before changing either producer.

## Data-preparation ref attributes

The anonymizer already stores a remote-image ref in `data-anon-image-ref-<attribute>`. The current ref resolver handles `image:` refs that replace an image value directly. It does not recognize `imageurl:` or use a sibling ref attribute to identify the placeholder that it must replace.

The current collector considers `src`, `rr_src`, and `poster`. Limit URL collection and sibling ref creation to `src` until the specification adds another source attribute.

The packed DOM serializer treats an unrecognized `data-*` attribute as model input and tokenizes its value. Without a new removal step, it will tokenize the ref hash.

Resolve the URL ref before rendering and tokenization. Use the sibling attribute's suffix as the destination attribute. Remove the sibling attribute after the lookup, including when the image is missing.

## Fetcher-to-scrubber record

The mirror currently sends an image to the scrub topic with the ref as the Kafka key and the raw image bytes as the Kafka value. It sends no JSON envelope. The scrubber accepts `image:` refs and rejects `imageurl:` refs.

The fetcher does not publish images yet. The server enforces dry-run mode.

Publish the fetched response body in the Kafka value and add the headers from section 17. The current fetcher requests `identity` and refuses another content coding. Change it to accept the codings it advertises and pass the encoded response body to Kafka.

Change the scrubber to accept a global `imageurl:` ref. Decode its `content-encoding` with an uncompressed-size limit, then check its bytes against `content-type` before scrubbing it.

The current scrubber writes every image into a binary shard and writes its location to a time-partitioned Parquet index. Store a URL-backed image at the deterministic object key from requirements 17.11 to 17.13 instead. Keep the shard and index path for inline images.

The current dead-letter sink rebuilds the headers from diagnostic data, and its replay keeps only the replay counter. Change both paths to preserve `content-type` and `content-encoding`.

The image-fetch producer currently uses the default Kafka message limit because its configuration has no `message.max.bytes` setting. Raise the configured response limit to 20 MiB and size the producer and both topics for that limit plus the maximum record overhead.

## Durable completion

The current fetcher records a successful fetch in DynamoDB without publishing its bytes. Change the handler to use the order in requirement 10.3.

The current frontier record does not carry all state needed after a redirect or retry. Replace it with the versioned job schema in requirement 10.4 and keep its counters and not-before time through every frontier and delay-topic publish.

The current crawl-history client can return partial read or write failures. The consumer logs these failures and continues. Change these paths to throw from the Kafka batch. Do not store the input offsets after a DynamoDB failure.

## Configuration caches

The current fetcher does not fetch or cache robots.txt or tdmrep.json.

The current request limits bound open sockets and the host-budget map. They do not coalesce concurrent cache misses for one origin. Add one in-flight configuration request per origin and file type. Other requests for that entry must wait for the same result.

Use `@trybyte/robotstxt-parser` with the product token `PostHogImageFetcherBot`. Use its low-level parser for every extension field line in addition to its RFC 9309 group and path matcher.

## URL admission

The current Rust collector removes userinfo before it emits the fetch URL. Change it to refuse the URL instead. The current collector also accepts several known pre-signed URL forms and removes their volatile parameters only from the dedup URL. Change it to refuse the pre-signed forms in requirement 1.2.

Keep only the non-credential volatile query fields from requirement 13.3 in canonicalization. Pin the complete canonicalization behavior with shared Rust and Node test vectors.

## Per-origin budgets

The current producer partitions the frontier by registrable domain. Keep that partition key so that every origin under the registrable domain has one steady-state pod owner.

Change the rate limit, concurrency limit, back-off, circuit breaker, and configuration request lock to use the origin. Use the registrable and provider domains only for Kafka ownership and bounded metrics.

The image-fetch server imports `KafkaConsumer` from `consumer-v1` directly. Move it to `KafkaConsumerV2`, whose cooperative revoke path drains the active batch before unassignment. Keep the bounded timeout exception from requirement 5.7. Do not add a distributed lease.

## Error back-off

The current host budget halves its rate after a failure, mixes refusals with transient failures, and does not have a half-open probe. Replace that behavior with the exact transient-failure count, jittered exponential delay, and half-open state in section 7. Configuration-file failures must not change this image-request state.

## Delay topics

The current delay consumer requires a batch size of 1 because it waits separately for each record. Change it to calculate the latest ready time for the batch, wait once, and then publish the batch.

The current delay topics do not require broker timestamps. Set `message.timestamp.type=LogAppendTime` on all three topics. The delay consumer must use the resulting Kafka record timestamp and must not use a producer timestamp.

The current publisher sends a delay longer than 1 hour through the 1-hour topic more than once. Change it to record a refusal when the required delay is longer than the longest delay topic.

## Load handling

The current consumer drops an input when its capture time is older than the configured maximum age. Remove this age-based drop.

The current fetch pass limits how many shed URLs it republishes. Remove this limit. Kafka stores load until the lane can process it. A pass deadline can stop new requests, but every unfinished URL must remain in Kafka.

## Repeated response headers

The current streamed-request helper keeps only the first value of a repeated response header. Change it to expose every field line in received order. Apply requirement 14.17 before parsing response-header opt-outs. Keeping only the first value can miss a later `X-Robots-Tag: noai` refusal.

## Same-origin redirect continuation

The current fetcher treats a fourth same-origin redirect as a terminal `too_many_redirects` result. Change it to republish the target with the original ref and remaining image-hop budget. Requirements 9.7 and 9.8 specify this behavior.

## Bounded origin state

The current budget map holds 20,000 entries. It can evict an origin while that origin is blocked. A later request creates a new entry with a full burst. That request can contact the origin before its `Retry-After` or breaker delay ends.

Change the map to evict only entries that meet requirement 5.14. If no entry is eligible, send the job for the untracked origin to the 1-minute delay topic without making a network request.

## Key-directory caching

The current Django key-directory response sends `Cache-Control: no-store`. Change it to the 60-second public cache policy in requirement 4.11 while keeping the 5-minute response-signature lifetime.
