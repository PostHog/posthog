import {
    KAFKA_CLICKHOUSE_AI_EVENTS_JSON,
    KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
    KAFKA_EVENTS_JSON,
    KAFKA_EVENTS_PLUGIN_INGESTION_ASYNC,
    KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
    KAFKA_GROUPS,
    KAFKA_INGESTION_WARNINGS,
} from '../../../config/kafka-topics'
import { DLQ_OUTPUT, GROUPS_OUTPUT, INGESTION_WARNINGS_OUTPUT, OVERFLOW_OUTPUT } from '../../common/outputs'
import { IngestionOutputDefinition } from '../../outputs/resolver'
import { AI_EVENTS_OUTPUT, ASYNC_OUTPUT, EVENTS_OUTPUT, HEATMAPS_OUTPUT } from '../outputs'
import { DEFAULT_PRODUCER, ProducerName } from './producers'

/** Static config for all analytics ingestion outputs. */
export const INGESTION_OUTPUT_DEFINITIONS: Record<string, IngestionOutputDefinition<ProducerName>> = {
    [EVENTS_OUTPUT]: {
        defaultTopic: KAFKA_EVENTS_JSON,
        defaultProducerName: DEFAULT_PRODUCER,
        producerOverrideEnvVar: 'INGESTION_OUTPUT_EVENTS_PRODUCER',
        topicOverrideEnvVar: 'INGESTION_OUTPUT_EVENTS_TOPIC',
    },
    [AI_EVENTS_OUTPUT]: {
        defaultTopic: KAFKA_CLICKHOUSE_AI_EVENTS_JSON,
        defaultProducerName: DEFAULT_PRODUCER,
        producerOverrideEnvVar: 'INGESTION_OUTPUT_AI_EVENTS_PRODUCER',
        topicOverrideEnvVar: 'INGESTION_OUTPUT_AI_EVENTS_TOPIC',
    },
    [HEATMAPS_OUTPUT]: {
        defaultTopic: KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
        defaultProducerName: DEFAULT_PRODUCER,
        producerOverrideEnvVar: 'INGESTION_OUTPUT_HEATMAPS_PRODUCER',
        topicOverrideEnvVar: 'INGESTION_OUTPUT_HEATMAPS_TOPIC',
    },
    [INGESTION_WARNINGS_OUTPUT]: {
        defaultTopic: KAFKA_INGESTION_WARNINGS,
        defaultProducerName: DEFAULT_PRODUCER,
        producerOverrideEnvVar: 'INGESTION_OUTPUT_INGESTION_WARNINGS_PRODUCER',
        topicOverrideEnvVar: 'INGESTION_OUTPUT_INGESTION_WARNINGS_TOPIC',
    },
    [DLQ_OUTPUT]: {
        defaultTopic: KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
        defaultProducerName: DEFAULT_PRODUCER,
        producerOverrideEnvVar: 'INGESTION_OUTPUT_DLQ_PRODUCER',
        topicOverrideEnvVar: 'INGESTION_OUTPUT_DLQ_TOPIC',
    },
    [OVERFLOW_OUTPUT]: {
        defaultTopic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
        defaultProducerName: DEFAULT_PRODUCER,
        producerOverrideEnvVar: 'INGESTION_OUTPUT_OVERFLOW_PRODUCER',
        topicOverrideEnvVar: 'INGESTION_OUTPUT_OVERFLOW_TOPIC',
    },
    [ASYNC_OUTPUT]: {
        defaultTopic: KAFKA_EVENTS_PLUGIN_INGESTION_ASYNC,
        defaultProducerName: DEFAULT_PRODUCER,
        producerOverrideEnvVar: 'INGESTION_OUTPUT_ASYNC_PRODUCER',
        topicOverrideEnvVar: 'INGESTION_OUTPUT_ASYNC_TOPIC',
    },
    [GROUPS_OUTPUT]: {
        defaultTopic: KAFKA_GROUPS,
        defaultProducerName: DEFAULT_PRODUCER,
        producerOverrideEnvVar: 'INGESTION_OUTPUT_GROUPS_PRODUCER',
        topicOverrideEnvVar: 'INGESTION_OUTPUT_GROUPS_TOPIC',
    },
}
