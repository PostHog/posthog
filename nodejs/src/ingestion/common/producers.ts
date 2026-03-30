import type { AllowedConfigKey } from '../outputs'

/**
 * DEFAULT uses the existing KAFKA_PRODUCER_* env vars — backwards compatible
 * with all existing deployments including dev and hobby.
 */
export const DEFAULT_PRODUCER = 'DEFAULT' as const
export type DefaultProducer = typeof DEFAULT_PRODUCER

/** Union of all known producer names. Extend this as new producers are added. */
export type ProducerName = DefaultProducer

/**
 * Mapping from rdkafka config key to env var name for each producer.
 * Each producer has a fixed set of env vars — no dynamic scanning.
 */
export const PRODUCER_CONFIG_MAP: Record<ProducerName, Partial<Record<AllowedConfigKey, string>>> = {
    [DEFAULT_PRODUCER]: {
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
    },
}
