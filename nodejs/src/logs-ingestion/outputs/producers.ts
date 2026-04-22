/**
 * Logs/traces ingestion producer names + their typed env-var config.
 *
 * Each producer is named explicitly after the cluster it targets so deployment
 * config is unambiguous. Env-var prefixes are preserved from the previous
 * implicit-target system (`KAFKA_PRODUCER_*`, `KAFKA_METRICS_PRODUCER_*`) so
 * deployed values continue to apply without coordination.
 */
import { AllowedConfigKey } from '../../ingestion/outputs/kafka-producer-config'

/**
 * Targets the legacy MSK cluster — used to write usage metrics back to
 * `clickhouse_app_metrics2` even though the main data path runs on Warpstream.
 */
export const MSK_PRODUCER = 'MSK_PRODUCER' as const
export type MskProducer = typeof MSK_PRODUCER

/**
 * Targets the Warpstream cluster dedicated to logs/traces. The main log/trace
 * data path produces here.
 */
export const WARPSTREAM_LOGS_PRODUCER = 'WARPSTREAM_LOGS_PRODUCER' as const
export type WarpstreamLogsProducer = typeof WARPSTREAM_LOGS_PRODUCER

/**
 * Targets the Warpstream cluster shared with the rest of ingestion. App
 * metrics will migrate from `MSK_PRODUCER` to here once routed via env var.
 */
export const WARPSTREAM_INGESTION_PRODUCER = 'WARPSTREAM_INGESTION_PRODUCER' as const
export type WarpstreamIngestionProducer = typeof WARPSTREAM_INGESTION_PRODUCER

/** Producer names registered by the logs/traces deployments. */
export type LogsProducerName = MskProducer | WarpstreamLogsProducer | WarpstreamIngestionProducer

/**
 * Mirrors the pre-existing `KAFKA_METRICS_PRODUCER_*` env vars so deployed
 * values continue to apply.
 */
export const MSK_PRODUCER_CONFIG_MAP = {
    'client.id': 'KAFKA_METRICS_PRODUCER_CLIENT_ID',
    'metadata.broker.list': 'KAFKA_METRICS_PRODUCER_METADATA_BROKER_LIST',
    'security.protocol': 'KAFKA_METRICS_PRODUCER_SECURITY_PROTOCOL',
    'sasl.mechanisms': 'KAFKA_METRICS_PRODUCER_SASL_MECHANISMS',
    'sasl.username': 'KAFKA_METRICS_PRODUCER_SASL_USERNAME',
    'sasl.password': 'KAFKA_METRICS_PRODUCER_SASL_PASSWORD',
    'compression.codec': 'KAFKA_METRICS_PRODUCER_COMPRESSION_CODEC',
    'linger.ms': 'KAFKA_METRICS_PRODUCER_LINGER_MS',
    'batch.size': 'KAFKA_METRICS_PRODUCER_BATCH_SIZE',
    'queue.buffering.max.messages': 'KAFKA_METRICS_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES',
    'queue.buffering.max.kbytes': 'KAFKA_METRICS_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES',
    'enable.ssl.certificate.verification': 'KAFKA_METRICS_PRODUCER_ENABLE_SSL_CERTIFICATE_VERIFICATION',
    'enable.idempotence': 'KAFKA_METRICS_PRODUCER_ENABLE_IDEMPOTENCE',
    'message.max.bytes': 'KAFKA_METRICS_PRODUCER_MESSAGE_MAX_BYTES',
    'batch.num.messages': 'KAFKA_METRICS_PRODUCER_BATCH_NUM_MESSAGES',
    'sticky.partitioning.linger.ms': 'KAFKA_METRICS_PRODUCER_STICKY_PARTITIONING_LINGER_MS',
    'topic.metadata.refresh.interval.ms': 'KAFKA_METRICS_PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS',
    'metadata.max.age.ms': 'KAFKA_METRICS_PRODUCER_METADATA_MAX_AGE_MS',
    'message.send.max.retries': 'KAFKA_METRICS_PRODUCER_RETRIES',
    'max.in.flight.requests.per.connection': 'KAFKA_METRICS_PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION',
} as const satisfies Partial<Record<AllowedConfigKey, string>>

/** Typed env vars referenced by `MSK_PRODUCER_CONFIG_MAP`. */
export type KafkaMskProducerEnvConfig = {
    KAFKA_METRICS_PRODUCER_CLIENT_ID: string
    KAFKA_METRICS_PRODUCER_METADATA_BROKER_LIST: string
    KAFKA_METRICS_PRODUCER_SECURITY_PROTOCOL: string
    KAFKA_METRICS_PRODUCER_SASL_MECHANISMS: string
    KAFKA_METRICS_PRODUCER_SASL_USERNAME: string
    KAFKA_METRICS_PRODUCER_SASL_PASSWORD: string
    KAFKA_METRICS_PRODUCER_COMPRESSION_CODEC: string
    KAFKA_METRICS_PRODUCER_LINGER_MS: string
    KAFKA_METRICS_PRODUCER_BATCH_SIZE: string
    KAFKA_METRICS_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES: string
    KAFKA_METRICS_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES: string
    KAFKA_METRICS_PRODUCER_ENABLE_SSL_CERTIFICATE_VERIFICATION: string
    KAFKA_METRICS_PRODUCER_ENABLE_IDEMPOTENCE: string
    KAFKA_METRICS_PRODUCER_MESSAGE_MAX_BYTES: string
    KAFKA_METRICS_PRODUCER_BATCH_NUM_MESSAGES: string
    KAFKA_METRICS_PRODUCER_STICKY_PARTITIONING_LINGER_MS: string
    KAFKA_METRICS_PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS: string
    KAFKA_METRICS_PRODUCER_METADATA_MAX_AGE_MS: string
    KAFKA_METRICS_PRODUCER_RETRIES: string
    KAFKA_METRICS_PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION: string
}

export function getDefaultKafkaMskProducerEnvConfig(): KafkaMskProducerEnvConfig {
    return {
        KAFKA_METRICS_PRODUCER_CLIENT_ID: '',
        KAFKA_METRICS_PRODUCER_METADATA_BROKER_LIST: '',
        KAFKA_METRICS_PRODUCER_SECURITY_PROTOCOL: '',
        KAFKA_METRICS_PRODUCER_SASL_MECHANISMS: '',
        KAFKA_METRICS_PRODUCER_SASL_USERNAME: '',
        KAFKA_METRICS_PRODUCER_SASL_PASSWORD: '',
        KAFKA_METRICS_PRODUCER_COMPRESSION_CODEC: '',
        KAFKA_METRICS_PRODUCER_LINGER_MS: '',
        KAFKA_METRICS_PRODUCER_BATCH_SIZE: '',
        KAFKA_METRICS_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES: '',
        KAFKA_METRICS_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES: '',
        KAFKA_METRICS_PRODUCER_ENABLE_SSL_CERTIFICATE_VERIFICATION: '',
        KAFKA_METRICS_PRODUCER_ENABLE_IDEMPOTENCE: '',
        KAFKA_METRICS_PRODUCER_MESSAGE_MAX_BYTES: '',
        KAFKA_METRICS_PRODUCER_BATCH_NUM_MESSAGES: '',
        KAFKA_METRICS_PRODUCER_STICKY_PARTITIONING_LINGER_MS: '',
        KAFKA_METRICS_PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS: '',
        KAFKA_METRICS_PRODUCER_METADATA_MAX_AGE_MS: '',
        KAFKA_METRICS_PRODUCER_RETRIES: '',
        KAFKA_METRICS_PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION: '',
    }
}

/**
 * Reuses the legacy `KAFKA_PRODUCER_*` env vars — that's what logs/traces
 * deployments already configure for their main data-path Warpstream producer.
 */
export const WARPSTREAM_LOGS_PRODUCER_CONFIG_MAP = {
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
