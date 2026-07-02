/** ML-mirror-specific config knobs, layered on top of the shared session-recording config. */
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

    /** Consumer group id for the image-scrub deployment that drains the image topic. */
    SESSION_RECORDING_ML_IMAGE_SCRUB_GROUP_ID: string
    /** S3 key prefix under the bucket for the scrubbed-image shards + index. */
    SESSION_RECORDING_ML_IMAGE_SCRUB_PREFIX: string
    /** Base URL of the co-located scrub sidecar (bytes -> scrubbed bytes). */
    SESSION_RECORDING_ML_IMAGE_SCRUB_SIDECAR_URL: string
    /** Roll up scrubbed images into one shard + index at least this often. Stays below max.poll.interval.ms. */
    SESSION_RECORDING_ML_IMAGE_SCRUB_FLUSH_INTERVAL_MS: number
    /** Image count that forces a flush before the interval (bounds memory). */
    SESSION_RECORDING_ML_IMAGE_SCRUB_MAX_IMAGES: number
    /** Buffered-bytes cap that forces a flush before the interval. */
    SESSION_RECORDING_ML_IMAGE_SCRUB_MAX_BYTES: number
    /** Max concurrent sidecar scrub requests in flight per batch. */
    SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_CONCURRENCY: number
    /** Per-request timeout for a sidecar scrub call. */
    SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_TIMEOUT_MS: number
    /** Retries on a transient (busy/network) sidecar failure before the batch replays. */
    SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_RETRIES: number
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
        SESSION_RECORDING_ML_IMAGE_SCRUB_GROUP_ID: 'session-replay-ml-image-scrub',
        SESSION_RECORDING_ML_IMAGE_SCRUB_PREFIX: 'scrubbed-images',
        SESSION_RECORDING_ML_IMAGE_SCRUB_SIDECAR_URL: 'http://localhost:9010',
        SESSION_RECORDING_ML_IMAGE_SCRUB_FLUSH_INTERVAL_MS: 30 * 1000,
        SESSION_RECORDING_ML_IMAGE_SCRUB_MAX_IMAGES: 1000,
        SESSION_RECORDING_ML_IMAGE_SCRUB_MAX_BYTES: 128 * 1024 * 1024,
        SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_CONCURRENCY: 8,
        SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_TIMEOUT_MS: 10 * 1000,
        SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_RETRIES: 3,
    }
}
