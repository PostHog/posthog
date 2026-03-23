import type { AllowedConfigKey } from '../kafka/producer-config'

/**
 * DEFAULT uses the existing KAFKA_PRODUCER_* env vars — backwards compatible
 * with all existing deployments including dev and hobby.
 */
export const DEFAULT_PRODUCER = 'DEFAULT' as const
export type DefaultProducer = typeof DEFAULT_PRODUCER

/** Union of all known producer names. Extend this as new producers are added. */
export type ProducerName = DefaultProducer

/**
 * Mapping from env var name to rdkafka config key for each producer.
 * Each producer has a fixed set of env vars — no dynamic scanning.
 */
export const PRODUCER_CONFIG_MAP: Record<ProducerName, Record<string, AllowedConfigKey>> = {
    [DEFAULT_PRODUCER]: {
        KAFKA_PRODUCER_METADATA_BROKER_LIST: 'metadata.broker.list',
        KAFKA_PRODUCER_SECURITY_PROTOCOL: 'security.protocol',
        KAFKA_PRODUCER_SASL_MECHANISMS: 'sasl.mechanisms',
        KAFKA_PRODUCER_SASL_USERNAME: 'sasl.username',
        KAFKA_PRODUCER_SASL_PASSWORD: 'sasl.password',
        KAFKA_PRODUCER_COMPRESSION_CODEC: 'compression.codec',
        KAFKA_PRODUCER_LINGER_MS: 'linger.ms',
        KAFKA_PRODUCER_BATCH_SIZE: 'batch.size',
        KAFKA_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES: 'queue.buffering.max.messages',
        KAFKA_PRODUCER_ENABLE_SSL_CERTIFICATE_VERIFICATION: 'enable.ssl.certificate.verification',
    },
}
