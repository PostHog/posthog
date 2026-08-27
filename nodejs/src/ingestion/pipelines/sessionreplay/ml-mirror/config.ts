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
     * Enabling changes the mirrored JSONL shape a second time. A direct remote image keeps its
     * placeholder and a `data-anon-image-ref-<attribute>` sibling carries its `imageurl:<hash>`
     * ref. CSS keeps numbered placeholders and a `data-anon-image-refs-<field>` sibling carries a
     * JSON slot-to-ref map. The URL hash names the URL rather than the bytes behind it.
     */
    SESSION_RECORDING_ML_URL_COLLECTION_ENABLED: boolean

    /**
     * Send the collected URLs to the fetch topic.
     *
     * This flag is separate from the collection flag, because the two steps have different risks.
     * Collection changes only the mirrored data. A produce puts original, unscrubbed URLs onto a
     * Kafka topic, so the fetch topic is as sensitive as the raw replay topic. Turn this flag on
     * only after the topic exists with the required retention and every fetch consumer accepts the
     * current ref format. The disabled default lets consumer support deploy before producers change.
     *
     * The flag does nothing unless SESSION_RECORDING_ML_URL_COLLECTION_ENABLED is also on, because
     * the anonymizer collects no URLs until then.
     */
    SESSION_RECORDING_ML_URL_PRODUCER_ENABLED: boolean
    /**
     * Read crawl history before the mirror sends URLs to Kafka.
     *
     * Read failures publish every candidate, so the lookup cannot lose fetch work.
     */
    SESSION_RECORDING_ML_URL_CRAWL_HISTORY_PRECHECK_ENABLED: boolean
    /** Bounds one producer-side crawl-history read. */
    SESSION_RECORDING_ML_URL_CRAWL_HISTORY_PRECHECK_TIMEOUT_MS: number

    // US-only, PEM, multiple keys allowed (comma-separated)
    WEB_BOT_AUTH_PRIVATE_KEYS: string

    /** While true, the fetch lane parses input but sends no request and writes no crawl history. */
    SESSION_RECORDING_ML_IMAGE_FETCH_DRY_RUN: boolean
    SESSION_RECORDING_ML_IMAGE_FETCH_GROUP_ID: string
    SESSION_RECORDING_ML_IMAGE_FETCH_BATCH_SIZE: number
    AI_RESEARCH_IMAGE_FETCH_DYNAMODB_TABLE: string
    /** Bounds one DynamoDB request so an unavailable store cannot hold the poll loop. */
    AI_RESEARCH_IMAGE_FETCH_DYNAMODB_TIMEOUT_MS: number
    /** TTL on each DynamoDB crawl-history entry, which sets the recrawl interval. */
    AI_RESEARCH_IMAGE_FETCH_CRAWL_HISTORY_TTL_SECONDS: number

    /** Optional steady request rate for one registrable domain. Zero uses the concurrency limit only. */
    SESSION_RECORDING_ML_IMAGE_FETCH_REGISTRABLE_DOMAIN_REQUESTS_PER_SECOND: number
    /** Tokens one idle registrable domain can retain when the steady request rate is enabled. */
    SESSION_RECORDING_ML_IMAGE_FETCH_REGISTRABLE_DOMAIN_BURST: number
    /** Also the worker count for one registrable domain or origin. */
    SESSION_RECORDING_ML_IMAGE_FETCH_MAX_CONCURRENT_PER_REGISTRABLE_DOMAIN: number
    /**
     * Requests this pod holds open across every registrable domain at once.
     *
     * The topic key sends one registrable domain to one partition and one pod. Its rate limit lives
     * on that pod. The state limits prevent unbounded in-memory maps.
     *
     * This bounds the pod instead. A body reads into a buffer, so the resident peak is roughly this
     * times SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IMAGE_BYTES, and the sockets and the DNS lookups
     * scale with it too. Raise the pod's memory before you raise this.
     */
    SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IN_FLIGHT_REQUESTS: number
    /** Low-diversity mode starts when the remaining request capacity is lower than this value. */
    SESSION_RECORDING_ML_IMAGE_FETCH_LOW_ORIGIN_DIVERSITY_MINIMUM_REQUEST_SLOTS: number
    /** Low-diversity mode starts only when more than this many undeferred canonical URL jobs remain. */
    SESSION_RECORDING_ML_IMAGE_FETCH_LOW_ORIGIN_DIVERSITY_REPUBLISH_THRESHOLD: number
    /** Canonical URL jobs fetched in low-diversity mode before the remaining undeferred jobs return to Kafka. */
    SESSION_RECORDING_ML_IMAGE_FETCH_LOW_ORIGIN_DIVERSITY_PROGRESS: number
    /** Image bodies waiting for Kafka delivery. This must fit inside the producer byte queue. */
    SESSION_RECORDING_ML_IMAGE_FETCH_MAX_PENDING_PUBLISHES: number
    /**
     * Wall time the fetch pass of one poll batch may take.
     *
     * A batch can hold more URLs for one registrable domain than a polite rate carries in this
     * time. What the pass does not reach goes to a delay topic without spending a hop. The value
     * sits well inside Kafka's max.poll.interval.ms of 300s, which the crawl history round trips
     * share.
     */
    SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_BUDGET_MS: number
    /** Refused before the body when the response declares more, and abandoned mid-body when it declares nothing. */
    SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IMAGE_BYTES: number
    /** Covers one URL including its redirects, separate from the connect timeout of the shared request layer. */
    SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_TIMEOUT_MS: number
    SESSION_RECORDING_ML_IMAGE_FETCH_MAX_REDIRECTS: number
    /** Consecutive failures before this pod stops sending to one registrable domain. */
    SESSION_RECORDING_ML_IMAGE_FETCH_REGISTRABLE_DOMAIN_BREAKER_FAILURES: number
    SESSION_RECORDING_ML_IMAGE_FETCH_REGISTRABLE_DOMAIN_BREAKER_COOLDOWN_MS: number
    /** The longest calculated breaker back-off. A longer valid `Retry-After` remains authoritative. */
    SESSION_RECORDING_ML_IMAGE_FETCH_REGISTRABLE_DOMAIN_BREAKER_MAX_COOLDOWN_MS: number
    /** Registrable domains one pod holds request-control state for. */
    SESSION_RECORDING_ML_IMAGE_FETCH_MAX_TRACKED_REGISTRABLE_DOMAINS: number
    /** Origins one pod holds configuration and crawl-delay state for. */
    SESSION_RECORDING_ML_IMAGE_FETCH_MAX_TRACKED_ORIGINS: number

    /**
     * The delay topic one retry pod drains, and the period every record in it waits.
     *
     * One server runs every tier, so three deployments of one image cover 1 minute, 10 minutes, and
     * one hour. The pod's `max.poll.interval.ms` must exceed the period, or the broker evicts the
     * consumer while it sleeps.
     */
    SESSION_RECORDING_ML_IMAGE_FETCH_RETRY_TOPIC: string
    SESSION_RECORDING_ML_IMAGE_FETCH_RETRY_DELAY_MS: number
    /** Records released together after one wait based on the latest broker append timestamp. */
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
        SESSION_RECORDING_ML_URL_CRAWL_HISTORY_PRECHECK_ENABLED: true,
        SESSION_RECORDING_ML_URL_CRAWL_HISTORY_PRECHECK_TIMEOUT_MS: 500,
        WEB_BOT_AUTH_PRIVATE_KEYS: '',
        SESSION_RECORDING_ML_IMAGE_FETCH_DRY_RUN: true,
        SESSION_RECORDING_ML_IMAGE_FETCH_GROUP_ID: 'session-replay-ml-image-fetch',
        SESSION_RECORDING_ML_IMAGE_FETCH_BATCH_SIZE: 500,
        AI_RESEARCH_IMAGE_FETCH_DYNAMODB_TABLE: '',
        AI_RESEARCH_IMAGE_FETCH_DYNAMODB_TIMEOUT_MS: 5_000,
        AI_RESEARCH_IMAGE_FETCH_CRAWL_HISTORY_TTL_SECONDS: 30 * 24 * 60 * 60,
        SESSION_RECORDING_ML_IMAGE_FETCH_REGISTRABLE_DOMAIN_REQUESTS_PER_SECOND: 0,
        SESSION_RECORDING_ML_IMAGE_FETCH_REGISTRABLE_DOMAIN_BURST: 6,
        SESSION_RECORDING_ML_IMAGE_FETCH_MAX_CONCURRENT_PER_REGISTRABLE_DOMAIN: 6,
        SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IN_FLIGHT_REQUESTS: 300,
        SESSION_RECORDING_ML_IMAGE_FETCH_LOW_ORIGIN_DIVERSITY_MINIMUM_REQUEST_SLOTS: 48,
        SESSION_RECORDING_ML_IMAGE_FETCH_LOW_ORIGIN_DIVERSITY_REPUBLISH_THRESHOLD: 50,
        SESSION_RECORDING_ML_IMAGE_FETCH_LOW_ORIGIN_DIVERSITY_PROGRESS: 8,
        SESSION_RECORDING_ML_IMAGE_FETCH_MAX_PENDING_PUBLISHES: 100,
        SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_BUDGET_MS: 40_000,
        SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IMAGE_BYTES: 20 * 1024 * 1024,
        SESSION_RECORDING_ML_IMAGE_FETCH_REQUEST_TIMEOUT_MS: 10_000,
        SESSION_RECORDING_ML_IMAGE_FETCH_MAX_REDIRECTS: 3,
        SESSION_RECORDING_ML_IMAGE_FETCH_REGISTRABLE_DOMAIN_BREAKER_FAILURES: 5,
        SESSION_RECORDING_ML_IMAGE_FETCH_REGISTRABLE_DOMAIN_BREAKER_COOLDOWN_MS: 60_000,
        SESSION_RECORDING_ML_IMAGE_FETCH_REGISTRABLE_DOMAIN_BREAKER_MAX_COOLDOWN_MS: 60 * 60 * 1000,
        SESSION_RECORDING_ML_IMAGE_FETCH_MAX_TRACKED_REGISTRABLE_DOMAINS: 20_000,
        SESSION_RECORDING_ML_IMAGE_FETCH_MAX_TRACKED_ORIGINS: 20_000,
        SESSION_RECORDING_ML_IMAGE_FETCH_RETRY_TOPIC: '',
        SESSION_RECORDING_ML_IMAGE_FETCH_RETRY_DELAY_MS: 60_000,
        SESSION_RECORDING_ML_IMAGE_FETCH_RETRY_BATCH_SIZE: 500,
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
