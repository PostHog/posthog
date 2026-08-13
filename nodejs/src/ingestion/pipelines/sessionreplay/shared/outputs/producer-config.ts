import type { AllowedConfigKey } from '~/common/outputs/kafka-producer-config'

/**
 * SESSIONREPLAY producer — the replay-domain Kafka cluster (warpstream-replay), carrying
 * replay events/features plus their DLQ and overflow. Replay-only, so it lives here rather
 * than in ingestion common (which only defines the cross-pipeline UPSTREAM/DOWNSTREAM slots).
 * Plaintext, in-cluster.
 */
export const INGESTION_SESSIONREPLAY_PRODUCER = 'INGESTION_SESSIONREPLAY' as const
export type IngestionSessionreplayProducer = typeof INGESTION_SESSIONREPLAY_PRODUCER

export const INGESTION_SESSIONREPLAY_PRODUCER_CONFIG_MAP = {
    'client.id': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_CLIENT_ID',
    'metadata.broker.list': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_METADATA_BROKER_LIST',
    'security.protocol': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_SECURITY_PROTOCOL',
    'compression.codec': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_COMPRESSION_CODEC',
    'linger.ms': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_LINGER_MS',
    'batch.size': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_BATCH_SIZE',
    'queue.buffering.max.messages': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES',
    'queue.buffering.max.kbytes': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES',
    'enable.idempotence': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_ENABLE_IDEMPOTENCE',
    'message.max.bytes': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_MESSAGE_MAX_BYTES',
    'batch.num.messages': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_BATCH_NUM_MESSAGES',
    'sticky.partitioning.linger.ms': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_STICKY_PARTITIONING_LINGER_MS',
    'topic.metadata.refresh.interval.ms': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS',
    'metadata.max.age.ms': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_METADATA_MAX_AGE_MS',
    'message.send.max.retries': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_RETRIES',
    'max.in.flight.requests.per.connection':
        'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION',
} as const satisfies Partial<Record<AllowedConfigKey, string>>

/**
 * Env var keys referenced by `INGESTION_SESSIONREPLAY_PRODUCER_CONFIG_MAP` plus the
 * ML_IMAGE_SCRUB producer's own tuning keys (its broker/security keys are shared with the
 * base map, so any server carrying this config can build both producers).
 */
export type KafkaSessionreplayProducerEnvConfig = Record<
    (typeof INGESTION_SESSIONREPLAY_PRODUCER_CONFIG_MAP)[keyof typeof INGESTION_SESSIONREPLAY_PRODUCER_CONFIG_MAP],
    string
> &
    KafkaMlImageScrubProducerEnvConfig &
    KafkaMlImageFetchProducerEnvConfig

export function getDefaultKafkaSessionreplayProducerEnvConfig(): KafkaSessionreplayProducerEnvConfig {
    return {
        ...getDefaultKafkaMlImageScrubProducerEnvConfig(),
        ...getDefaultKafkaMlImageFetchProducerEnvConfig(),
        KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_CLIENT_ID: '',
        KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_METADATA_BROKER_LIST: '',
        KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_SECURITY_PROTOCOL: '',
        KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_COMPRESSION_CODEC: '',
        KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_LINGER_MS: '',
        KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_BATCH_SIZE: '',
        KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES: '',
        KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES: '',
        KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_ENABLE_IDEMPOTENCE: '',
        KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_MESSAGE_MAX_BYTES: '',
        KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_BATCH_NUM_MESSAGES: '',
        KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_STICKY_PARTITIONING_LINGER_MS: '',
        KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS: '',
        KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_METADATA_MAX_AGE_MS: '',
        KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_RETRIES: '',
        KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION: '',
    }
}

/**
 * ML_IMAGE_SCRUB producer — same replay cluster, but a dedicated client instance so the
 * image-scrub lane's heavy, best-effort payloads (original image bytes, up to 32 MB per source
 * message) buffer in their own librdkafka queue. A scrub-topic slowdown then fails fast inside
 * this producer (failed produces are swallowed by design — a dangling ref reads as a placeholder)
 * instead of filling the shared SESSIONREPLAY queue and starving DLQ/overflow/metadata produces.
 * Broker/security config is shared with the SESSIONREPLAY producer; only the buffering knobs and
 * compression differ (image bytes are already compressed, so codec defaults to none).
 */
export const INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER = 'INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB' as const
export type IngestionSessionreplayMlImageScrubProducer = typeof INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER

export const INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_CONFIG_MAP = {
    'client.id': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_CLIENT_ID',
    'metadata.broker.list': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_METADATA_BROKER_LIST',
    'security.protocol': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_SECURITY_PROTOCOL',
    'compression.codec': 'KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_COMPRESSION_CODEC',
    'linger.ms': 'KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_LINGER_MS',
    'queue.buffering.max.messages':
        'KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES',
    'queue.buffering.max.kbytes': 'KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES',
    'message.max.bytes': 'KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_MESSAGE_MAX_BYTES',
    'message.timeout.ms': 'KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_MESSAGE_TIMEOUT_MS',
} as const satisfies Partial<Record<AllowedConfigKey, string>>

/** Env var keys owned by `INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_CONFIG_MAP` (broker/security keys are shared). */
export type KafkaMlImageScrubProducerEnvConfig = {
    KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_COMPRESSION_CODEC: string
    KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_LINGER_MS: string
    KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES: string
    KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES: string
    KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_MESSAGE_MAX_BYTES: string
    KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_MESSAGE_TIMEOUT_MS: string
}

export function getDefaultKafkaMlImageScrubProducerEnvConfig(): KafkaMlImageScrubProducerEnvConfig {
    return {
        // Image bytes are already-compressed formats; recompressing burns CPU for nothing.
        KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_COMPRESSION_CODEC: 'none',
        KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_LINGER_MS: '',
        // Small queue by design: bounds the lane's RSS ceiling (~128 MB of ~900 KB records — four
        // worst-case 32 MB source messages) and makes a scrub-topic backlog fail fast in this
        // producer instead of accumulating.
        KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES: '10000',
        KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES: '131072',
        KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_MESSAGE_MAX_BYTES: '',
        // Short local delivery timeout (librdkafka defaults to 300s): the lane is best-effort and
        // its ack promises join the mirror's pre-commit side-effect drain, so a scrub-topic
        // slowdown must fail deliveries fast (dangling ref = placeholder) rather than stall the
        // mirror's offset commits toward max.poll.interval.ms.
        KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_MESSAGE_TIMEOUT_MS: '20000',
    }
}

/**
 * ML_IMAGE_FETCH producer — the fetch lane's own client instance on the replay cluster.
 *
 * It does not share the ML_IMAGE_SCRUB producer, whose settings are tuned for the opposite payload.
 * That producer sets `compression.codec: none`, which is right for image bytes that are already
 * compressed and wrong for a record of JSON URLs, which compress well. Its queue is also sized in
 * messages for a lane whose records are ~900 KB each, so this lane's much smaller records would
 * share a byte budget shaped for something else, and a scrub-topic backlog would fail URL produces
 * that have nothing to do with it.
 *
 * Broker and security config are shared with the SESSIONREPLAY producer, as on the scrub lane.
 */
export const INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER = 'INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH' as const
export type IngestionSessionreplayMlImageFetchProducer = typeof INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER

export const INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER_CONFIG_MAP = {
    'client.id': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_CLIENT_ID',
    'metadata.broker.list': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_METADATA_BROKER_LIST',
    'security.protocol': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_SECURITY_PROTOCOL',
    'compression.codec': 'KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER_COMPRESSION_CODEC',
    'linger.ms': 'KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER_LINGER_MS',
    'queue.buffering.max.messages':
        'KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES',
    'queue.buffering.max.kbytes': 'KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES',
    'message.timeout.ms': 'KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER_MESSAGE_TIMEOUT_MS',
} as const satisfies Partial<Record<AllowedConfigKey, string>>

export type KafkaMlImageFetchProducerEnvConfig = {
    KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER_COMPRESSION_CODEC: string
    KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER_LINGER_MS: string
    KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES: string
    KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES: string
    KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER_MESSAGE_TIMEOUT_MS: string
}

export function getDefaultKafkaMlImageFetchProducerEnvConfig(): KafkaMlImageFetchProducerEnvConfig {
    return {
        // JSON URLs compress well, unlike the image bytes on the scrub lane.
        KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER_COMPRESSION_CODEC: 'snappy',
        KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER_LINGER_MS: '',
        // A record is packed to a byte budget, so bytes rather than count are what bind here:
        // this holds roughly 60 full records in flight against 50,000 small ones.
        KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES: '50000',
        KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES: '32768',
        // The same short local timeout as the scrub lane, and for the same reason: these ack
        // promises join the mirror's pre-commit side-effect drain, so a slow topic must fail fast
        // rather than hold the mirror's offset commits toward max.poll.interval.ms.
        KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER_MESSAGE_TIMEOUT_MS: '20000',
    }
}
