import os from 'node:os'

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
     * Produce collected original images to the scrub topic. Enabling changes the mirrored JSONL
     * shape: image fields carry `image:<pseudoTeam>:<hash>` refs instead of blurred data URIs, so
     * both the scrub consumer lane AND ref-aware downstream readers must be live first.
     */
    SESSION_RECORDING_ML_IMAGE_SCRUB_PRODUCER_ENABLED: boolean
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
     * partition-affine and a per-pod cache dedupes them exactly up to this many refs (~200 B each in
     * a Map, so 1M ≈ 200 MB). 0 disables dedup.
     */
    SESSION_RECORDING_ML_IMAGE_SCRUB_DEDUP_MAX_REFS: number
    SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_TIMEOUT_MS: number
    SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_RETRIES: number
    // Per-write timeout (the S3 client has no built-in one). A flush does two writes, so it bounds at 2x this.
    SESSION_RECORDING_ML_IMAGE_SCRUB_S3_WRITE_TIMEOUT_MS: number
    // Scrub-phase budget, covering scrub time only — mid-batch flush time is excluded (each flush is
    // separately bounded at 2x the S3 write timeout). Sized so scrub plus the worst-case flushes for
    // one poll batch stays under Kafka's max.poll.interval.ms (300s), or a hung sidecar/S3 evicts us
    // mid-batch and livelocks.
    SESSION_RECORDING_ML_IMAGE_SCRUB_MAX_BATCH_SCRUB_MS: number

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
        SESSION_RECORDING_ML_IMAGE_SCRUB_PRODUCER_ENABLED: false,
        SESSION_RECORDING_ML_IMAGE_SCRUB_GROUP_ID: 'session-replay-ml-image-scrub',
        SESSION_RECORDING_ML_IMAGE_SCRUB_PREFIX: 'scrubbed-images',
        // 127.0.0.1, not localhost: the sidecar binds IPv4 loopback, and localhost can resolve to ::1 first.
        SESSION_RECORDING_ML_IMAGE_SCRUB_SIDECAR_URL: 'http://127.0.0.1:9010',
        SESSION_RECORDING_ML_IMAGE_SCRUB_FLUSH_INTERVAL_MS: 30 * 1000,
        SESSION_RECORDING_ML_IMAGE_SCRUB_MAX_IMAGES: 1000,
        SESSION_RECORDING_ML_IMAGE_SCRUB_MAX_BYTES: 128 * 1024 * 1024,
        SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_CONCURRENCY: 8,
        SESSION_RECORDING_ML_IMAGE_SCRUB_DEDUP_MAX_REFS: 1_000_000,
        SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_TIMEOUT_MS: 10 * 1000,
        SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_RETRIES: 3,
        SESSION_RECORDING_ML_IMAGE_SCRUB_S3_WRITE_TIMEOUT_MS: 30 * 1000,
        SESSION_RECORDING_ML_IMAGE_SCRUB_MAX_BATCH_SCRUB_MS: 120 * 1000,
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
