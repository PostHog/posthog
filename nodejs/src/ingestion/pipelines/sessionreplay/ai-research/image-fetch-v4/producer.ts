import { TOPHOG_OUTPUT, TophogOutput } from '~/common/outputs'
import { IngestionOutputsBuilder } from '~/common/outputs/ingestion-outputs-builder'
import type { AllowedConfigKey } from '~/common/outputs/kafka-producer-config'
import { KafkaProducerRegistryBuilder } from '~/common/outputs/kafka-producer-registry-builder'
import {
    INGESTION_DOWNSTREAM_PRODUCER,
    INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP,
    IngestionDownstreamProducer,
} from '~/ingestion/common/outputs/producers'

/**
 * The v4 fetch lane's own producer on the replay cluster. It sends frontier records to the frontier and the delay tiers
 * in a queue of its own. Broker and security config are those of the replay producer.
 */
export const AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER = 'AI_RESEARCH_V4_IMAGE_FETCH' as const

export const AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_CONFIG_MAP = {
    'client.id': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_CLIENT_ID',
    'metadata.broker.list': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_METADATA_BROKER_LIST',
    'security.protocol': 'KAFKA_INGESTION_SESSIONREPLAY_PRODUCER_SECURITY_PROTOCOL',
    'compression.codec': 'KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_COMPRESSION_CODEC',
    'linger.ms': 'KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_LINGER_MS',
    'queue.buffering.max.messages': 'KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES',
    'queue.buffering.max.kbytes': 'KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_QUEUE_BUFFERING_MAX_KBYTES',
    'message.max.bytes': 'KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_MESSAGE_MAX_BYTES',
    'message.timeout.ms': 'KAFKA_AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_MESSAGE_TIMEOUT_MS',
} as const satisfies Partial<Record<AllowedConfigKey, string>>

/** DOWNSTREAM carries the TopHog rows to ClickHouse. */
export type AiResearchV4ImageFetchProducerName =
    | IngestionDownstreamProducer
    | typeof AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER

type ProducerConfigKey =
    | (typeof INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP)[keyof typeof INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP]
    | (typeof AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_CONFIG_MAP)[keyof typeof AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_CONFIG_MAP]

export function createV4ImageFetchProducerRegistry(
    kafkaClientRack: string | undefined
): KafkaProducerRegistryBuilder<AiResearchV4ImageFetchProducerName, ProducerConfigKey> {
    return new KafkaProducerRegistryBuilder(kafkaClientRack)
        .register(INGESTION_DOWNSTREAM_PRODUCER, INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP)
        .register(AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER, AI_RESEARCH_V4_IMAGE_FETCH_PRODUCER_CONFIG_MAP)
}

export function createV4ImageFetchOutputs(): IngestionOutputsBuilder<
    TophogOutput,
    'AI_RESEARCH_V4_IMAGE_FETCH_TOPHOG_TOPIC',
    'AI_RESEARCH_V4_IMAGE_FETCH_TOPHOG_PRODUCER'
> {
    return new IngestionOutputsBuilder().register(TOPHOG_OUTPUT, {
        topicKey: 'AI_RESEARCH_V4_IMAGE_FETCH_TOPHOG_TOPIC',
        producerKey: 'AI_RESEARCH_V4_IMAGE_FETCH_TOPHOG_PRODUCER',
    })
}
