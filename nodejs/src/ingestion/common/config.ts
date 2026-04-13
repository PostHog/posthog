import type { AllowedConfigKey } from '../outputs/kafka-producer-config'

/**
 * Mapping from rdkafka config key to config object key for the default producer.
 *
 * `as const` preserves the literal key names so the builder can enforce at compile time
 * that the config object contains every referenced key.
 */
export const DEFAULT_PRODUCER_CONFIG_MAP = {
    'client.id': 'KAFKA_PRODUCER_CLIENT_ID',
    'metadata.broker.list': 'KAFKA_PRODUCER_METADATA_BROKER_LIST',
    'security.protocol': 'KAFKA_PRODUCER_SECURITY_PROTOCOL',
    'sasl.mechanisms': 'KAFKA_PRODUCER_SASL_MECHANISMS',
    'sasl.username': 'KAFKA_PRODUCER_SASL_USERNAME',
    'sasl.password': 'KAFKA_PRODUCER_SASL_PASSWORD',
    'compression.codec': 'KAFKA_PRODUCER_COMPRESSION_CODEC',
    'linger.ms': 'KAFKA_PRODUCER_LINGER_MS',
    'batch.size': 'KAFKA_PRODUCER_BATCH_SIZE',
    'queue.buffering.max.messages': 'KAFKA_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES',
    'queue.buffering.max.kbytes': 'KAFKA_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES',
    'enable.ssl.certificate.verification': 'KAFKA_PRODUCER_ENABLE_SSL_CERTIFICATE_VERIFICATION',
    'enable.idempotence': 'KAFKA_PRODUCER_ENABLE_IDEMPOTENCE',
    'message.max.bytes': 'KAFKA_PRODUCER_MESSAGE_MAX_BYTES',
    'batch.num.messages': 'KAFKA_PRODUCER_BATCH_NUM_MESSAGES',
    'sticky.partitioning.linger.ms': 'KAFKA_PRODUCER_STICKY_PARTITIONING_LINGER_MS',
    'topic.metadata.refresh.interval.ms': 'KAFKA_PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS',
    'metadata.max.age.ms': 'KAFKA_PRODUCER_METADATA_MAX_AGE_MS',
    'message.send.max.retries': 'KAFKA_PRODUCER_RETRIES',
    'max.in.flight.requests.per.connection': 'KAFKA_PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION',
} as const satisfies Partial<Record<AllowedConfigKey, string>>

/** The config keys referenced by `DEFAULT_PRODUCER_CONFIG_MAP`. */
export type DefaultProducerConfigKey = (typeof DEFAULT_PRODUCER_CONFIG_MAP)[keyof typeof DEFAULT_PRODUCER_CONFIG_MAP]

/**
 * WARPSTREAM runs in-cluster over plaintext — no SASL auth or SSL verification needed.
 *
 * Buffering/batching settings (linger.ms, batch.size, queue.buffering.*, batch.num.messages,
 * sticky.partitioning.linger.ms) are kept identical to DEFAULT because our produce path
 * awaits the delivery callback per message, so librdkafka batching has no practical effect
 * until we move to a fire-and-forget pattern.
 */
export const WARPSTREAM_PRODUCER_CONFIG_MAP = {
    'client.id': 'KAFKA_WARPSTREAM_PRODUCER_CLIENT_ID',
    'metadata.broker.list': 'KAFKA_WARPSTREAM_PRODUCER_METADATA_BROKER_LIST',
    'security.protocol': 'KAFKA_WARPSTREAM_PRODUCER_SECURITY_PROTOCOL',
    'compression.codec': 'KAFKA_WARPSTREAM_PRODUCER_COMPRESSION_CODEC',
    'linger.ms': 'KAFKA_WARPSTREAM_PRODUCER_LINGER_MS',
    'batch.size': 'KAFKA_WARPSTREAM_PRODUCER_BATCH_SIZE',
    'queue.buffering.max.messages': 'KAFKA_WARPSTREAM_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES',
    'queue.buffering.max.kbytes': 'KAFKA_WARPSTREAM_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES',
    'enable.idempotence': 'KAFKA_WARPSTREAM_PRODUCER_ENABLE_IDEMPOTENCE',
    'message.max.bytes': 'KAFKA_WARPSTREAM_PRODUCER_MESSAGE_MAX_BYTES',
    'batch.num.messages': 'KAFKA_WARPSTREAM_PRODUCER_BATCH_NUM_MESSAGES',
    'sticky.partitioning.linger.ms': 'KAFKA_WARPSTREAM_PRODUCER_STICKY_PARTITIONING_LINGER_MS',
    'topic.metadata.refresh.interval.ms': 'KAFKA_WARPSTREAM_PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS',
    'metadata.max.age.ms': 'KAFKA_WARPSTREAM_PRODUCER_METADATA_MAX_AGE_MS',
    'message.send.max.retries': 'KAFKA_WARPSTREAM_PRODUCER_RETRIES',
    'max.in.flight.requests.per.connection': 'KAFKA_WARPSTREAM_PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION',
} as const satisfies Partial<Record<AllowedConfigKey, string>>

/** The config keys referenced by `WARPSTREAM_PRODUCER_CONFIG_MAP`. */
export type WarpstreamProducerConfigKey =
    (typeof WARPSTREAM_PRODUCER_CONFIG_MAP)[keyof typeof WARPSTREAM_PRODUCER_CONFIG_MAP]

/** Kafka producer env var config — keys referenced by `DEFAULT_PRODUCER_CONFIG_MAP` */
export type KafkaProducerEnvConfig = {
    KAFKA_PRODUCER_CLIENT_ID: string
    KAFKA_PRODUCER_METADATA_BROKER_LIST: string
    KAFKA_PRODUCER_SECURITY_PROTOCOL: string
    KAFKA_PRODUCER_SASL_MECHANISMS: string
    KAFKA_PRODUCER_SASL_USERNAME: string
    KAFKA_PRODUCER_SASL_PASSWORD: string
    KAFKA_PRODUCER_COMPRESSION_CODEC: string
    KAFKA_PRODUCER_LINGER_MS: string
    KAFKA_PRODUCER_BATCH_SIZE: string
    KAFKA_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES: string
    KAFKA_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES: string
    KAFKA_PRODUCER_ENABLE_SSL_CERTIFICATE_VERIFICATION: string
    KAFKA_PRODUCER_ENABLE_IDEMPOTENCE: string
    KAFKA_PRODUCER_MESSAGE_MAX_BYTES: string
    KAFKA_PRODUCER_BATCH_NUM_MESSAGES: string
    KAFKA_PRODUCER_STICKY_PARTITIONING_LINGER_MS: string
    KAFKA_PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS: string
    KAFKA_PRODUCER_METADATA_MAX_AGE_MS: string
    KAFKA_PRODUCER_RETRIES: string
    KAFKA_PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION: string
}

/** Kafka WarpStream producer env var config — keys referenced by `WARPSTREAM_PRODUCER_CONFIG_MAP` */
export type KafkaWarpstreamProducerEnvConfig = {
    KAFKA_WARPSTREAM_PRODUCER_CLIENT_ID: string
    KAFKA_WARPSTREAM_PRODUCER_METADATA_BROKER_LIST: string
    KAFKA_WARPSTREAM_PRODUCER_SECURITY_PROTOCOL: string
    KAFKA_WARPSTREAM_PRODUCER_COMPRESSION_CODEC: string
    KAFKA_WARPSTREAM_PRODUCER_LINGER_MS: string
    KAFKA_WARPSTREAM_PRODUCER_BATCH_SIZE: string
    KAFKA_WARPSTREAM_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES: string
    KAFKA_WARPSTREAM_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES: string
    KAFKA_WARPSTREAM_PRODUCER_ENABLE_IDEMPOTENCE: string
    KAFKA_WARPSTREAM_PRODUCER_MESSAGE_MAX_BYTES: string
    KAFKA_WARPSTREAM_PRODUCER_BATCH_NUM_MESSAGES: string
    KAFKA_WARPSTREAM_PRODUCER_STICKY_PARTITIONING_LINGER_MS: string
    KAFKA_WARPSTREAM_PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS: string
    KAFKA_WARPSTREAM_PRODUCER_METADATA_MAX_AGE_MS: string
    KAFKA_WARPSTREAM_PRODUCER_RETRIES: string
    KAFKA_WARPSTREAM_PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION: string
}

export function getDefaultKafkaProducerEnvConfig(): KafkaProducerEnvConfig {
    return {
        KAFKA_PRODUCER_CLIENT_ID: '',
        KAFKA_PRODUCER_METADATA_BROKER_LIST: '',
        KAFKA_PRODUCER_SECURITY_PROTOCOL: '',
        KAFKA_PRODUCER_SASL_MECHANISMS: '',
        KAFKA_PRODUCER_SASL_USERNAME: '',
        KAFKA_PRODUCER_SASL_PASSWORD: '',
        KAFKA_PRODUCER_COMPRESSION_CODEC: '',
        KAFKA_PRODUCER_LINGER_MS: '',
        KAFKA_PRODUCER_BATCH_SIZE: '',
        KAFKA_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES: '',
        KAFKA_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES: '',
        KAFKA_PRODUCER_ENABLE_SSL_CERTIFICATE_VERIFICATION: '',
        KAFKA_PRODUCER_ENABLE_IDEMPOTENCE: '',
        KAFKA_PRODUCER_MESSAGE_MAX_BYTES: '',
        KAFKA_PRODUCER_BATCH_NUM_MESSAGES: '',
        KAFKA_PRODUCER_STICKY_PARTITIONING_LINGER_MS: '',
        KAFKA_PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS: '',
        KAFKA_PRODUCER_METADATA_MAX_AGE_MS: '',
        KAFKA_PRODUCER_RETRIES: '',
        KAFKA_PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION: '',
    }
}

export function getDefaultKafkaWarpstreamProducerEnvConfig(): KafkaWarpstreamProducerEnvConfig {
    return {
        KAFKA_WARPSTREAM_PRODUCER_CLIENT_ID: '',
        KAFKA_WARPSTREAM_PRODUCER_METADATA_BROKER_LIST: '',
        KAFKA_WARPSTREAM_PRODUCER_SECURITY_PROTOCOL: '',
        KAFKA_WARPSTREAM_PRODUCER_COMPRESSION_CODEC: '',
        KAFKA_WARPSTREAM_PRODUCER_LINGER_MS: '',
        KAFKA_WARPSTREAM_PRODUCER_BATCH_SIZE: '',
        KAFKA_WARPSTREAM_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES: '',
        KAFKA_WARPSTREAM_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES: '',
        KAFKA_WARPSTREAM_PRODUCER_ENABLE_IDEMPOTENCE: '',
        KAFKA_WARPSTREAM_PRODUCER_MESSAGE_MAX_BYTES: '',
        KAFKA_WARPSTREAM_PRODUCER_BATCH_NUM_MESSAGES: '',
        KAFKA_WARPSTREAM_PRODUCER_STICKY_PARTITIONING_LINGER_MS: '',
        KAFKA_WARPSTREAM_PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS: '',
        KAFKA_WARPSTREAM_PRODUCER_METADATA_MAX_AGE_MS: '',
        KAFKA_WARPSTREAM_PRODUCER_RETRIES: '',
        KAFKA_WARPSTREAM_PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION: '',
    }
}
