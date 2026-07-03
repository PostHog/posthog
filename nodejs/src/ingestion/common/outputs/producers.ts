import type { AllowedConfigKey } from '~/common/outputs/kafka-producer-config'

// Producer names
//
// A producer name is a named Kafka connection slot, not a fixed cluster: the code declares the
// slots, and each pipeline's Helm charts wire a slot to a concrete cluster (broker list +
// security protocol) and route its outputs to it. A slot can map to different clusters in
// different pipelines. The slot → cluster mapping lives in the charts repo
// (shared/ingestion/common*.yaml, argocd/ingestion/config/*.yaml).
//
// Cluster-accurate slots:
//   INGESTION_UPSTREAM   — dedicated ingestion cluster; re-consumed topics (overflow/async/dlq)
//   INGESTION_DOWNSTREAM — warpstream-ingestion cluster; ClickHouse-bound outputs
// Pipeline-specific slots (e.g. session replay's warpstream-replay producer) live in their own module.

/** UPSTREAM — dedicated ingestion cluster; re-consumed topics (overflow/async/dlq). */
export const INGESTION_UPSTREAM_PRODUCER = 'INGESTION_UPSTREAM' as const
export type IngestionUpstreamProducer = typeof INGESTION_UPSTREAM_PRODUCER

/** DOWNSTREAM — warpstream-ingestion cluster; ClickHouse-bound outputs. */
export const INGESTION_DOWNSTREAM_PRODUCER = 'INGESTION_DOWNSTREAM' as const
export type IngestionDownstreamProducer = typeof INGESTION_DOWNSTREAM_PRODUCER

/** Union of all known producer names. Extend this as new producers are added. */
export type ProducerName = IngestionUpstreamProducer | IngestionDownstreamProducer

// =============================================================================
// Cluster-accurate producer slots: env-var maps and their default env config.
// =============================================================================

/** UPSTREAM — dedicated ingestion cluster (re-consumed topics); ssl + sasl auth. */
export const INGESTION_UPSTREAM_PRODUCER_CONFIG_MAP = {
    'client.id': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_CLIENT_ID',
    'metadata.broker.list': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_METADATA_BROKER_LIST',
    'security.protocol': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_SECURITY_PROTOCOL',
    'sasl.mechanisms': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_SASL_MECHANISMS',
    'sasl.username': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_SASL_USERNAME',
    'sasl.password': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_SASL_PASSWORD',
    'compression.codec': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_COMPRESSION_CODEC',
    'linger.ms': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_LINGER_MS',
    'batch.size': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_BATCH_SIZE',
    'queue.buffering.max.messages': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES',
    'queue.buffering.max.kbytes': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES',
    'enable.ssl.certificate.verification': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_ENABLE_SSL_CERTIFICATE_VERIFICATION',
    'enable.idempotence': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_ENABLE_IDEMPOTENCE',
    'message.max.bytes': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_MESSAGE_MAX_BYTES',
    'batch.num.messages': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_BATCH_NUM_MESSAGES',
    'sticky.partitioning.linger.ms': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_STICKY_PARTITIONING_LINGER_MS',
    'topic.metadata.refresh.interval.ms': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS',
    'metadata.max.age.ms': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_METADATA_MAX_AGE_MS',
    'message.send.max.retries': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_RETRIES',
    'max.in.flight.requests.per.connection': 'KAFKA_INGESTION_UPSTREAM_PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION',
} as const satisfies Partial<Record<AllowedConfigKey, string>>

/** DOWNSTREAM — warpstream-ingestion cluster (ClickHouse-bound); in-cluster plaintext. */
export const INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP = {
    'client.id': 'KAFKA_INGESTION_DOWNSTREAM_PRODUCER_CLIENT_ID',
    'metadata.broker.list': 'KAFKA_INGESTION_DOWNSTREAM_PRODUCER_METADATA_BROKER_LIST',
    'security.protocol': 'KAFKA_INGESTION_DOWNSTREAM_PRODUCER_SECURITY_PROTOCOL',
    'compression.codec': 'KAFKA_INGESTION_DOWNSTREAM_PRODUCER_COMPRESSION_CODEC',
    'linger.ms': 'KAFKA_INGESTION_DOWNSTREAM_PRODUCER_LINGER_MS',
    'batch.size': 'KAFKA_INGESTION_DOWNSTREAM_PRODUCER_BATCH_SIZE',
    'queue.buffering.max.messages': 'KAFKA_INGESTION_DOWNSTREAM_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES',
    'queue.buffering.max.kbytes': 'KAFKA_INGESTION_DOWNSTREAM_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES',
    'enable.idempotence': 'KAFKA_INGESTION_DOWNSTREAM_PRODUCER_ENABLE_IDEMPOTENCE',
    'message.max.bytes': 'KAFKA_INGESTION_DOWNSTREAM_PRODUCER_MESSAGE_MAX_BYTES',
    'batch.num.messages': 'KAFKA_INGESTION_DOWNSTREAM_PRODUCER_BATCH_NUM_MESSAGES',
    'sticky.partitioning.linger.ms': 'KAFKA_INGESTION_DOWNSTREAM_PRODUCER_STICKY_PARTITIONING_LINGER_MS',
    'topic.metadata.refresh.interval.ms': 'KAFKA_INGESTION_DOWNSTREAM_PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS',
    'metadata.max.age.ms': 'KAFKA_INGESTION_DOWNSTREAM_PRODUCER_METADATA_MAX_AGE_MS',
    'message.send.max.retries': 'KAFKA_INGESTION_DOWNSTREAM_PRODUCER_RETRIES',
    'max.in.flight.requests.per.connection':
        'KAFKA_INGESTION_DOWNSTREAM_PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION',
} as const satisfies Partial<Record<AllowedConfigKey, string>>

/** Env var config for the UPSTREAM slot — keys derived from the config map above. */
export type KafkaUpstreamProducerEnvConfig = Record<
    (typeof INGESTION_UPSTREAM_PRODUCER_CONFIG_MAP)[keyof typeof INGESTION_UPSTREAM_PRODUCER_CONFIG_MAP],
    string
>

/** Env var config for the DOWNSTREAM slot — keys derived from the config map above. */
export type KafkaDownstreamProducerEnvConfig = Record<
    (typeof INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP)[keyof typeof INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP],
    string
>

/** Defaults for the UPSTREAM slot — every key '' so unset keys fall through to schema defaults. */
export function getDefaultKafkaUpstreamProducerEnvConfig(): KafkaUpstreamProducerEnvConfig {
    return {
        KAFKA_INGESTION_UPSTREAM_PRODUCER_CLIENT_ID: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_METADATA_BROKER_LIST: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_SECURITY_PROTOCOL: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_SASL_MECHANISMS: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_SASL_USERNAME: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_SASL_PASSWORD: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_COMPRESSION_CODEC: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_LINGER_MS: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_BATCH_SIZE: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_ENABLE_SSL_CERTIFICATE_VERIFICATION: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_ENABLE_IDEMPOTENCE: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_MESSAGE_MAX_BYTES: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_BATCH_NUM_MESSAGES: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_STICKY_PARTITIONING_LINGER_MS: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_METADATA_MAX_AGE_MS: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_RETRIES: '',
        KAFKA_INGESTION_UPSTREAM_PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION: '',
    }
}

/** Defaults for the DOWNSTREAM slot — every key '' so unset keys fall through to schema defaults. */
export function getDefaultKafkaDownstreamProducerEnvConfig(): KafkaDownstreamProducerEnvConfig {
    return {
        KAFKA_INGESTION_DOWNSTREAM_PRODUCER_CLIENT_ID: '',
        KAFKA_INGESTION_DOWNSTREAM_PRODUCER_METADATA_BROKER_LIST: '',
        KAFKA_INGESTION_DOWNSTREAM_PRODUCER_SECURITY_PROTOCOL: '',
        KAFKA_INGESTION_DOWNSTREAM_PRODUCER_COMPRESSION_CODEC: '',
        KAFKA_INGESTION_DOWNSTREAM_PRODUCER_LINGER_MS: '',
        KAFKA_INGESTION_DOWNSTREAM_PRODUCER_BATCH_SIZE: '',
        KAFKA_INGESTION_DOWNSTREAM_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES: '',
        KAFKA_INGESTION_DOWNSTREAM_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES: '',
        KAFKA_INGESTION_DOWNSTREAM_PRODUCER_ENABLE_IDEMPOTENCE: '',
        KAFKA_INGESTION_DOWNSTREAM_PRODUCER_MESSAGE_MAX_BYTES: '',
        KAFKA_INGESTION_DOWNSTREAM_PRODUCER_BATCH_NUM_MESSAGES: '',
        KAFKA_INGESTION_DOWNSTREAM_PRODUCER_STICKY_PARTITIONING_LINGER_MS: '',
        KAFKA_INGESTION_DOWNSTREAM_PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS: '',
        KAFKA_INGESTION_DOWNSTREAM_PRODUCER_METADATA_MAX_AGE_MS: '',
        KAFKA_INGESTION_DOWNSTREAM_PRODUCER_RETRIES: '',
        KAFKA_INGESTION_DOWNSTREAM_PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION: '',
    }
}
