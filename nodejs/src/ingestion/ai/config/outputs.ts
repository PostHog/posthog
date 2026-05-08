import {
    KAFKA_APP_METRICS_2,
    KAFKA_CLICKHOUSE_AI_EVENTS_JSON,
    KAFKA_CLICKHOUSE_TOPHOG,
    KAFKA_EVENTS_JSON,
    KAFKA_EVENTS_PLUGIN_INGESTION_ASYNC,
    KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
    KAFKA_GROUPS,
    KAFKA_INGESTION_WARNINGS,
    KAFKA_PERSON,
    KAFKA_PERSON_DISTINCT_ID,
} from '../../../config/kafka-topics'
import {
    AI_EVENTS_OUTPUT,
    ASYNC_OUTPUT,
    EVENTS_OUTPUT,
    PERSONS_OUTPUT,
    PERSON_DISTINCT_IDS_OUTPUT,
} from '../../analytics/outputs'
import {
    APP_METRICS_OUTPUT,
    DEFAULT_PRODUCER,
    DLQ_OUTPUT,
    GROUPS_OUTPUT,
    INGESTION_WARNINGS_OUTPUT,
    OVERFLOW_OUTPUT,
    type ProducerName,
    TOPHOG_OUTPUT,
} from '../../common/outputs'
import { IngestionOutputsBuilder } from '../../outputs/ingestion-outputs-builder'

export type AiOutputsConfig = {
    AI_OUTPUT_EVENTS_TOPIC: string
    AI_OUTPUT_EVENTS_PRODUCER: ProducerName
    AI_OUTPUT_AI_EVENTS_TOPIC: string
    AI_OUTPUT_AI_EVENTS_PRODUCER: ProducerName
    AI_OUTPUT_INGESTION_WARNINGS_TOPIC: string
    AI_OUTPUT_INGESTION_WARNINGS_PRODUCER: ProducerName
    AI_OUTPUT_DLQ_TOPIC: string
    AI_OUTPUT_DLQ_PRODUCER: ProducerName
    AI_OUTPUT_OVERFLOW_TOPIC: string
    AI_OUTPUT_OVERFLOW_PRODUCER: ProducerName
    AI_OUTPUT_ASYNC_TOPIC: string
    AI_OUTPUT_ASYNC_PRODUCER: ProducerName
    AI_OUTPUT_GROUPS_TOPIC: string
    AI_OUTPUT_GROUPS_PRODUCER: ProducerName
    AI_OUTPUT_PERSONS_TOPIC: string
    AI_OUTPUT_PERSONS_PRODUCER: ProducerName
    AI_OUTPUT_PERSON_DISTINCT_IDS_TOPIC: string
    AI_OUTPUT_PERSON_DISTINCT_IDS_PRODUCER: ProducerName
    AI_OUTPUT_APP_METRICS_TOPIC: string
    AI_OUTPUT_APP_METRICS_PRODUCER: ProducerName
    AI_OUTPUT_TOPHOG_TOPIC: string
    AI_OUTPUT_TOPHOG_PRODUCER: ProducerName
}

export function getDefaultAiOutputsConfig(): AiOutputsConfig {
    return {
        AI_OUTPUT_EVENTS_TOPIC: KAFKA_EVENTS_JSON,
        AI_OUTPUT_EVENTS_PRODUCER: DEFAULT_PRODUCER,
        AI_OUTPUT_AI_EVENTS_TOPIC: KAFKA_CLICKHOUSE_AI_EVENTS_JSON,
        AI_OUTPUT_AI_EVENTS_PRODUCER: DEFAULT_PRODUCER,
        AI_OUTPUT_INGESTION_WARNINGS_TOPIC: KAFKA_INGESTION_WARNINGS,
        AI_OUTPUT_INGESTION_WARNINGS_PRODUCER: DEFAULT_PRODUCER,
        AI_OUTPUT_DLQ_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
        AI_OUTPUT_DLQ_PRODUCER: DEFAULT_PRODUCER,
        AI_OUTPUT_OVERFLOW_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
        AI_OUTPUT_OVERFLOW_PRODUCER: DEFAULT_PRODUCER,
        AI_OUTPUT_ASYNC_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION_ASYNC,
        AI_OUTPUT_ASYNC_PRODUCER: DEFAULT_PRODUCER,
        AI_OUTPUT_GROUPS_TOPIC: KAFKA_GROUPS,
        AI_OUTPUT_GROUPS_PRODUCER: DEFAULT_PRODUCER,
        AI_OUTPUT_PERSONS_TOPIC: KAFKA_PERSON,
        AI_OUTPUT_PERSONS_PRODUCER: DEFAULT_PRODUCER,
        AI_OUTPUT_PERSON_DISTINCT_IDS_TOPIC: KAFKA_PERSON_DISTINCT_ID,
        AI_OUTPUT_PERSON_DISTINCT_IDS_PRODUCER: DEFAULT_PRODUCER,
        AI_OUTPUT_APP_METRICS_TOPIC: KAFKA_APP_METRICS_2,
        AI_OUTPUT_APP_METRICS_PRODUCER: DEFAULT_PRODUCER,
        AI_OUTPUT_TOPHOG_TOPIC: KAFKA_CLICKHOUSE_TOPHOG,
        AI_OUTPUT_TOPHOG_PRODUCER: DEFAULT_PRODUCER,
    }
}

/**
 * Register the outputs the AI pipeline writes to.
 *
 * Simple register (topic + producer) — no dual-write surface. AI is a new
 * consumer with no active migration; dual-write would just add env-var noise.
 */
export function registerAiOutputs() {
    return new IngestionOutputsBuilder()
        .register(EVENTS_OUTPUT, {
            topicKey: 'AI_OUTPUT_EVENTS_TOPIC',
            producerKey: 'AI_OUTPUT_EVENTS_PRODUCER',
        })
        .register(AI_EVENTS_OUTPUT, {
            topicKey: 'AI_OUTPUT_AI_EVENTS_TOPIC',
            producerKey: 'AI_OUTPUT_AI_EVENTS_PRODUCER',
        })
        .register(INGESTION_WARNINGS_OUTPUT, {
            topicKey: 'AI_OUTPUT_INGESTION_WARNINGS_TOPIC',
            producerKey: 'AI_OUTPUT_INGESTION_WARNINGS_PRODUCER',
        })
        .register(DLQ_OUTPUT, {
            topicKey: 'AI_OUTPUT_DLQ_TOPIC',
            producerKey: 'AI_OUTPUT_DLQ_PRODUCER',
        })
        .register(OVERFLOW_OUTPUT, {
            topicKey: 'AI_OUTPUT_OVERFLOW_TOPIC',
            producerKey: 'AI_OUTPUT_OVERFLOW_PRODUCER',
        })
        .register(ASYNC_OUTPUT, {
            topicKey: 'AI_OUTPUT_ASYNC_TOPIC',
            producerKey: 'AI_OUTPUT_ASYNC_PRODUCER',
        })
        .register(GROUPS_OUTPUT, {
            topicKey: 'AI_OUTPUT_GROUPS_TOPIC',
            producerKey: 'AI_OUTPUT_GROUPS_PRODUCER',
        })
        .register(PERSONS_OUTPUT, {
            topicKey: 'AI_OUTPUT_PERSONS_TOPIC',
            producerKey: 'AI_OUTPUT_PERSONS_PRODUCER',
        })
        .register(PERSON_DISTINCT_IDS_OUTPUT, {
            topicKey: 'AI_OUTPUT_PERSON_DISTINCT_IDS_TOPIC',
            producerKey: 'AI_OUTPUT_PERSON_DISTINCT_IDS_PRODUCER',
        })
        .register(APP_METRICS_OUTPUT, {
            topicKey: 'AI_OUTPUT_APP_METRICS_TOPIC',
            producerKey: 'AI_OUTPUT_APP_METRICS_PRODUCER',
        })
        .register(TOPHOG_OUTPUT, {
            topicKey: 'AI_OUTPUT_TOPHOG_TOPIC',
            producerKey: 'AI_OUTPUT_TOPHOG_PRODUCER',
        })
}
