import {
    KAFKA_CLICKHOUSE_AI_EVENTS_JSON,
    KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
    KAFKA_EVENTS_JSON,
} from '../../../config/kafka-topics'
import { IngestionOutputDefinition } from '../../outputs/resolver'
import { AI_EVENTS_OUTPUT, EVENTS_OUTPUT, HEATMAPS_OUTPUT } from '../outputs'
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
}
