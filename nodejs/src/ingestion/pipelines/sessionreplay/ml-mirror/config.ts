import os from 'node:os'

import { KAFKA_SESSION_REPLAY_IMAGE_SCRUB_DLQ } from '~/common/config/kafka-topics'
import { RedisConnectionConfig } from '~/common/utils/db/redis'

export type MlMirrorConfig = {
    /** S3 key prefix under the bucket for the block-metadata Parquet dataset (used by the sink). */
    SESSION_RECORDING_ML_METADATA_PREFIX: string
    /** Optional S3 key of the `{ text, url }` allow-list document; empty → in-binary defaults. */
    SESSION_RECORDING_ML_ALLOW_LIST_S3_KEY: string
    /** Plaintext HMAC secret to pseudonymize ids; for local dev only — prod uses the KMS-wrapped key below. */
    SESSION_RECORDING_ML_PSEUDONYM_SECRET: string
    /** Base64 KMS-encrypted pseudonym key (envelope); decrypted once at startup, never persisted. Preferred over the plaintext secret. */
    SESSION_RECORDING_ML_PSEUDONYM_WRAPPED_KEY: string
    /** AWS region for the KMS Decrypt call; empty → the SDK default credential/region chain. */
    SESSION_RECORDING_ML_PSEUDONYM_KMS_REGION: string
    /** Expected key fingerprint; if set, startup fails when the resolved key's fingerprint differs (enforces never-rotate). */
    SESSION_RECORDING_ML_PSEUDONYM_KEY_FINGERPRINT: string
    /** Consumer group id for the Parquet-sink deployment that drains the metadata topic. */
    SESSION_RECORDING_ML_PARQUET_SINK_GROUP_ID: string
    /**
     * The sink rolls up rows and writes one Parquet object at least this often (fewer, larger S3 objects).
     * Must stay comfortably below `max.poll.interval.ms` (300s) — the flush runs inline on the poll loop.
     */
    SESSION_RECORDING_ML_PARQUET_FLUSH_INTERVAL_MS: number
    /** Row cap that forces a flush before the interval elapses (bounds the sink's memory). */
    SESSION_RECORDING_ML_PARQUET_MAX_ROWS: number

    /**
     * Host of a Redis dedicated to this lane. Empty sends the mirror to the shared session-replay
     * cluster instead, so clearing this value is the supported rollback.
     *
     * The mirror's per-session keys otherwise sit on the cluster that also serves the primary replay
     * lane, so memory pressure from the mirror reaches the lane that gates replay ingestion. Pointing
     * the mirror at its own instance removes that path.
     */
    SESSION_RECORDING_ML_REDIS_HOST: string
    SESSION_RECORDING_ML_REDIS_PORT: number

    /**
     * Produce collected original images to the scrub topic. Enabling changes the mirrored JSONL
     * shape: image fields carry `image:<pseudoTeam>:<hash>` refs instead of blurred data URIs, so
     * both the scrub consumer lane AND ref-aware downstream readers must be live first.
     */
    SESSION_RECORDING_ML_IMAGE_SCRUB_PRODUCER_ENABLED: boolean

    /**
     * Collect the URLs of remote images as well, so the fetch lane can download them later.
     *
     * Enabling changes the mirrored JSONL shape a second time: a remote image keeps its grey
     * placeholder and a `data-anon-image-ref-<attribute>` sibling carries its
     * `imageurl:<pseudoTeam>:<hash>` ref. The prefix differs from the image lane's `image:` on
     * purpose, because this hash names the URL rather than the bytes behind it. Nothing fetches
     * those URLs yet, so every such ref is dangling. What this buys is the measurement of how many
     * URLs and how many distinct hosts real traffic carries.
     */
    SESSION_RECORDING_ML_URL_COLLECTION_ENABLED: boolean

    /**
     * Send the collected URLs to the fetch topic.
     *
     * This flag is separate from the collection flag, because the two steps have different risks.
     * Collection changes only the mirrored data. A produce puts original, unscrubbed URLs onto a
     * Kafka topic, so the fetch topic is as sensitive as the raw replay topic. Turn this flag on
     * only after the topic exists with the retention that section 2.5 of the plan gives it.
     *
     * The flag does nothing unless SESSION_RECORDING_ML_URL_COLLECTION_ENABLED is also on, because
     * the anonymizer collects no URLs until then.
     */
    SESSION_RECORDING_ML_URL_PRODUCER_ENABLED: boolean

    // US-only, PEM, multiple keys allowed (comma-separated)
    WEB_BOT_AUTH_PRIVATE_KEYS: string

    /**
     * While true the fetch lane sends no outbound request. It reads the topic, dedupes, writes the
     * ledger and reports the metrics, which is the phase 0 measurement: how many requests the
     * fetcher would offer, and how many of those dedup away before one is needed.
     *
     * Turning it off makes this deployment send requests to customer sites, so it stays on until
     * those numbers have been read and the per-site budget has been sized against them.
     */
    SESSION_RECORDING_ML_IMAGE_FETCH_DRY_RUN: boolean
    SESSION_RECORDING_ML_IMAGE_FETCH_GROUP_ID: string
    SESSION_RECORDING_ML_IMAGE_FETCH_BATCH_SIZE: number
    /** A URL older than this is dropped, so a lane with a backlog sheds work rather than fetching stale work. */
    SESSION_RECORDING_ML_IMAGE_FETCH_MAX_AGE_MS: number
    /** Capacity of the per-pod seen-ref cache that sits in front of the crawl history. */
    SESSION_RECORDING_ML_IMAGE_FETCH_DEDUP_MAX_REFS: number
    AI_RESEARCH_IMAGE_FETCH_DYNAMODB_TABLE: string
    /** Bounds one DynamoDB request so an unavailable store cannot hold the poll loop. */
    AI_RESEARCH_IMAGE_FETCH_DYNAMODB_TIMEOUT_MS: number
    /** TTL on each DynamoDB crawl-history entry, which sets the recrawl interval. */
    AI_RESEARCH_IMAGE_FETCH_CRAWL_HISTORY_TTL_SECONDS: number

    /**
     * What one registrable domain receives from one pod.
     *
     * Every value below is a politeness control, so all of them are environment variables. An
     * incident must change the load this lane puts on a customer site in minutes, and a deploy
     * takes longer than that.
     *
     * One request each second is far below the rate a browser puts on the same site. This lane
     * works at that rate because one fetch serves every session that refers to the image, and
     * because nothing waits on the result.
     */
    SESSION_RECORDING_ML_IMAGE_FETCH_REQUESTS_PER_SECOND: number
    /** Tokens a domain holds while idle, so a site seen once an hour gets a short run rather than one request. */
    SESSION_RECORDING_ML_IMAGE_FETCH_BURST: number
    /** Also the worker count of one back queue, so the connection limit and the worker count cannot disagree. */
    SESSION_RECORDING_ML_IMAGE_FETCH_MAX_CONCURRENT_PER_DOMAIN: number
    /**
     * Requests this pod holds open across every domain at once.
     *
     * Nothing caps the number of domains, because the topic keys by registrable domain, so a domain
     * lands on one partition and one pod, and its rate limit lives there. A pod that owns many
     * domains must serve them all, because each has its own allowance and none waits on the others.
     *
     * This bounds the pod instead. A body reads into a buffer, so the resident peak is roughly this
     * times SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IMAGE_BYTES, and the sockets and the DNS lookups
     * scale with it too. Raise the pod's memory before you raise this.
     */
    SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IN_FLIGHT_REQUESTS: number
    /**
     * Wall time the fetch pass of one poll batch may take.
     *
     * A batch can hold more URLs for one domain than a polite rate carries in this time. What the
     * pass does not reach goes to a delay topic and spends a hop. The value sits well inside Kafka's
     * max.poll.interval.ms of 300s, which the crawl history round trips share.
     */
    SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_BUDGET_MS: number
    /** Refused before the body when the response declares more, and abandoned mid-body when it declares nothing. */
    SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IMAGE_BYTES: number
    /** Covers one URL including its redirects, separate from the connect timeout of the shared request layer. */
    SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_TIMEOUT_MS: number
    SESSION_RECORDING_ML_IMAGE_FETCH_MAX_REDIRECTS: number
    /** Consecutive failures of one domain before this pod stops sending to it. */
    SESSION_RECORDING_ML_IMAGE_FETCH_BREAKER_FAILURES: number
    SESSION_RECORDING_ML_IMAGE_FETCH_BREAKER_COOLDOWN_MS: number
    /** The longest a domain stays blocked, whether the breaker or a site's own `Retry-After` blocked it. */
    SESSION_RECORDING_ML_IMAGE_FETCH_BREAKER_MAX_COOLDOWN_MS: number
    /** Held after a 429 or a 503 that named no period. */
    SESSION_RECORDING_ML_IMAGE_FETCH_DEFAULT_RETRY_AFTER_MS: number
    /** Domains one pod holds rate-limit state for. Past this the least recently used entry goes, and the pod forgets that the domain was blocked. */
    SESSION_RECORDING_ML_IMAGE_FETCH_MAX_TRACKED_DOMAINS: number

    /**
     * The delay topic one retry pod drains, and the period every record in it waits.
     *
     * One server runs every tier, so three deployments of one image cover 1 minute, 10 minutes, and
     * one hour. The pod's `max.poll.interval.ms` must exceed the period, or the broker evicts the
     * consumer while it sleeps.
     */
    SESSION_RECORDING_ML_IMAGE_FETCH_RETRY_TOPIC: string
    SESSION_RECORDING_ML_IMAGE_FETCH_RETRY_DELAY_MS: number
    /**
     * One record per batch, so the poll interval the server computes is exact.
     *
     * A batch of many records can hold records written hours apart, and that batch waits once for
     * each of them. Sizing the poll interval for that case means multiplying the tier's period by
     * the batch size, which soon passes what Kafka accepts at the 1 hour tier.
     */
    SESSION_RECORDING_ML_IMAGE_FETCH_RETRY_BATCH_SIZE: number

    /**
     * Capacity of the mirror's produced-URL ref cache, which bounds re-produces onto the fetch
     * topic. Tunable for the same reason as its image-lane twin below: it trades memory for topic
     * volume, so a mirror memory incident must be able to shed it without a code deploy.
     */
    SESSION_RECORDING_ML_URL_PRODUCED_REF_CACHE_MAX: number
    SESSION_RECORDING_ML_IMAGE_SCRUB_GROUP_ID: string
    SESSION_RECORDING_ML_IMAGE_SCRUB_PREFIX: string
    SESSION_RECORDING_ML_IMAGE_SCRUB_SIDECAR_URL: string
    SESSION_RECORDING_ML_IMAGE_SCRUB_FLUSH_INTERVAL_MS: number
    SESSION_RECORDING_ML_IMAGE_SCRUB_MAX_IMAGES: number
    // Real peak memory is ~2x this: the flush does a Buffer.concat copy.
    SESSION_RECORDING_ML_IMAGE_SCRUB_MAX_BYTES: number
    SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_CONCURRENCY: number
    /**
     * Capacity of the consumer's per-pod seen-ref LRU. The topic is keyed by ref, so duplicates are
     * partition-affine and a per-pod cache dedupes them exactly up to this many refs. Budget ~200 B
     * per entry, of which lru-cache commits about an eighth up front by preallocating its backing
     * arrays. Sized against the 2000M consumer container in
     * https://github.com/PostHog/charts/blob/main/apps/ingestion-sessionreplay-ml-image-scrub/values.yaml,
     * which also has to hold MAX_BYTES of scrubbed images at ~2x during a flush. Start low and raise
     * it off ml_mirror_ref_cache_capacity_probe_total rather than guessing.
     *
     * 0 disables only this cross-batch cache; duplicates within a poll batch always collapse.
     */
    SESSION_RECORDING_ML_IMAGE_SCRUB_DEDUP_MAX_REFS: number
    /**
     * The mirror-side twin of the knob above, bounding re-produces onto the scrub topic. Tunable for
     * the same reason: it is a pure memory-for-throughput trade, and shedding it during a mirror
     * memory incident should not need a code deploy of the shared replay ingester.
     */
    SESSION_RECORDING_ML_IMAGE_SCRUB_PRODUCED_REF_CACHE_MAX: number
    /**
     * How long to wait for the sidecar to answer one image.
     *
     * Must exceed the sidecar's own IMAGE_SCRUB_JOB_TIMEOUT_MS plus the time a request can sit in
     * its admission queue, and the ordering is load-bearing rather than a matter of taste. The
     * sidecar answers a job it cannot finish by retiring the worker and returning 500, which is a
     * considered answer about that image and is what lets a genuinely unprocessable one be blamed
     * and parked. Give up first and that answer never arrives: the image looks merely slow on every
     * attempt, never earns blame, and sits at the head of a partition shared by every team whose
     * records hash to it. A timeout is then what it should be, the sidecar saying nothing at all.
     */
    SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_TIMEOUT_MS: number
    /** Where images the sidecar cannot process are parked so they stop holding their partition. */
    SESSION_RECORDING_ML_IMAGE_SCRUB_DLQ_TOPIC: string
    /** Messages per poll. Bounds batch wall time against Kafka's max.poll.interval.ms (300s). */
    SESSION_RECORDING_ML_IMAGE_SCRUB_BATCH_SIZE: number
    // Per-write timeout (the S3 client has no built-in one). A flush does two writes, so it bounds at 2x this.
    SESSION_RECORDING_ML_IMAGE_SCRUB_S3_WRITE_TIMEOUT_MS: number
    /**
     * Cap on messages scrubbed concurrently per pod. Each in-flight scrub occupies one libuv
     * threadpool thread (UV_THREADPOOL_SIZE, default 4, shared with the recorder's snappy
     * compression). <= 0 (the default) resolves to min(available CPUs, threadpool size); an
     * explicit positive value is used verbatim; 1 restores fully sequential scrubbing.
     */
    SESSION_RECORDING_ML_ANONYMIZE_MAX_CONCURRENCY: number
}

export function getDefaultMlMirrorConfig(): MlMirrorConfig {
    return {
        SESSION_RECORDING_ML_METADATA_PREFIX: 'block-metadata',
        SESSION_RECORDING_ML_ALLOW_LIST_S3_KEY: '',
        SESSION_RECORDING_ML_PSEUDONYM_SECRET: '',
        SESSION_RECORDING_ML_PSEUDONYM_WRAPPED_KEY: '',
        SESSION_RECORDING_ML_PSEUDONYM_KMS_REGION: '',
        SESSION_RECORDING_ML_PSEUDONYM_KEY_FINGERPRINT: '',
        SESSION_RECORDING_ML_PARQUET_SINK_GROUP_ID: 'session-replay-ml-parquet-sink',
        SESSION_RECORDING_ML_PARQUET_FLUSH_INTERVAL_MS: 60 * 1000,
        SESSION_RECORDING_ML_PARQUET_MAX_ROWS: 250_000,
        SESSION_RECORDING_ML_REDIS_HOST: '',
        SESSION_RECORDING_ML_REDIS_PORT: 6379,
        SESSION_RECORDING_ML_IMAGE_SCRUB_PRODUCER_ENABLED: false,
        SESSION_RECORDING_ML_URL_COLLECTION_ENABLED: false,
        SESSION_RECORDING_ML_URL_PRODUCER_ENABLED: false,
        WEB_BOT_AUTH_PRIVATE_KEYS: '',
        SESSION_RECORDING_ML_IMAGE_FETCH_DRY_RUN: true,
        SESSION_RECORDING_ML_IMAGE_FETCH_GROUP_ID: 'session-replay-ml-image-fetch',
        SESSION_RECORDING_ML_IMAGE_FETCH_BATCH_SIZE: 500,
        SESSION_RECORDING_ML_IMAGE_FETCH_MAX_AGE_MS: 6 * 60 * 60 * 1000,
        SESSION_RECORDING_ML_IMAGE_FETCH_DEDUP_MAX_REFS: 500_000,
        AI_RESEARCH_IMAGE_FETCH_DYNAMODB_TABLE: '',
        AI_RESEARCH_IMAGE_FETCH_DYNAMODB_TIMEOUT_MS: 5_000,
        AI_RESEARCH_IMAGE_FETCH_CRAWL_HISTORY_TTL_SECONDS: 30 * 24 * 60 * 60,
        SESSION_RECORDING_ML_IMAGE_FETCH_REQUESTS_PER_SECOND: 1,
        SESSION_RECORDING_ML_IMAGE_FETCH_BURST: 5,
        SESSION_RECORDING_ML_IMAGE_FETCH_MAX_CONCURRENT_PER_DOMAIN: 6,
        SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IN_FLIGHT_REQUESTS: 300,
        SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_BUDGET_MS: 20_000,
        SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IMAGE_BYTES: 2 * 1024 * 1024,
        SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_TIMEOUT_MS: 10_000,
        SESSION_RECORDING_ML_IMAGE_FETCH_MAX_REDIRECTS: 3,
        SESSION_RECORDING_ML_IMAGE_FETCH_BREAKER_FAILURES: 5,
        SESSION_RECORDING_ML_IMAGE_FETCH_BREAKER_COOLDOWN_MS: 60_000,
        SESSION_RECORDING_ML_IMAGE_FETCH_BREAKER_MAX_COOLDOWN_MS: 2 * 60 * 60 * 1000,
        SESSION_RECORDING_ML_IMAGE_FETCH_DEFAULT_RETRY_AFTER_MS: 60_000,
        SESSION_RECORDING_ML_IMAGE_FETCH_MAX_TRACKED_DOMAINS: 20_000,
        SESSION_RECORDING_ML_IMAGE_FETCH_RETRY_TOPIC: '',
        SESSION_RECORDING_ML_IMAGE_FETCH_RETRY_DELAY_MS: 60_000,
        SESSION_RECORDING_ML_IMAGE_FETCH_RETRY_BATCH_SIZE: 1,
        SESSION_RECORDING_ML_URL_PRODUCED_REF_CACHE_MAX: 500_000,
        SESSION_RECORDING_ML_IMAGE_SCRUB_GROUP_ID: 'session-replay-ml-image-scrub',
        SESSION_RECORDING_ML_IMAGE_SCRUB_PREFIX: 'scrubbed-images',
        // 127.0.0.1, not localhost: the sidecar binds IPv4 loopback, and localhost can resolve to ::1 first.
        SESSION_RECORDING_ML_IMAGE_SCRUB_SIDECAR_URL: 'http://127.0.0.1:9010',
        SESSION_RECORDING_ML_IMAGE_SCRUB_FLUSH_INTERVAL_MS: 30 * 1000,
        SESSION_RECORDING_ML_IMAGE_SCRUB_MAX_IMAGES: 1000,
        SESSION_RECORDING_ML_IMAGE_SCRUB_MAX_BYTES: 128 * 1024 * 1024,
        SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_CONCURRENCY: 8,
        SESSION_RECORDING_ML_IMAGE_SCRUB_DEDUP_MAX_REFS: 250_000,
        SESSION_RECORDING_ML_IMAGE_SCRUB_PRODUCED_REF_CACHE_MAX: 500_000,
        SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_TIMEOUT_MS: 45 * 1000,
        SESSION_RECORDING_ML_IMAGE_SCRUB_DLQ_TOPIC: KAFKA_SESSION_REPLAY_IMAGE_SCRUB_DLQ,
        SESSION_RECORDING_ML_IMAGE_SCRUB_BATCH_SIZE: 50,
        SESSION_RECORDING_ML_IMAGE_SCRUB_S3_WRITE_TIMEOUT_MS: 30 * 1000,
        SESSION_RECORDING_ML_ANONYMIZE_MAX_CONCURRENCY: 0,
    }
}

const DEFAULT_UV_THREADPOOL_SIZE = 4

/**
 * `os.availableParallelism()` respects cgroup CPU limits, so in-container this sees the pod's
 * cores, not the node's.
 */
export function resolveMlAnonymizeMaxConcurrency(
    configured: number,
    availableParallelism: number = os.availableParallelism(),
    uvThreadpoolSize: number = parseInt(process.env.UV_THREADPOOL_SIZE ?? '', 10) || DEFAULT_UV_THREADPOOL_SIZE
): number {
    if (configured > 0) {
        return configured
    }
    return Math.max(1, Math.min(availableParallelism, uvThreadpoolSize))
}

/**
 * A host of whitespace counts as unset: chart values render to an empty string when the underlying
 * secret key is missing, and connecting to `""` would fail every command rather than return `null`.
 */
export function resolveMlMirrorRedisConnection(
    config: Pick<MlMirrorConfig, 'SESSION_RECORDING_ML_REDIS_HOST' | 'SESSION_RECORDING_ML_REDIS_PORT'> & {
        SESSION_RECORDING_REDIS_TIMEOUT_MS: number
    }
): RedisConnectionConfig | null {
    const host = config.SESSION_RECORDING_ML_REDIS_HOST.trim()
    if (!host) {
        return null
    }
    return {
        url: host,
        options: {
            port: config.SESSION_RECORDING_ML_REDIS_PORT,
            commandTimeout: config.SESSION_RECORDING_REDIS_TIMEOUT_MS,
        },
        name: 'session-recording-ml-redis',
    }
}
