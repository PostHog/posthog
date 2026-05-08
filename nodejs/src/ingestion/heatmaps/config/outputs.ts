import {
    KAFKA_APP_METRICS_2,
    KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
    KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
    KAFKA_GROUPS,
    KAFKA_INGESTION_WARNINGS,
    KAFKA_PERSON,
    KAFKA_PERSON_DISTINCT_ID,
} from '../../../config/kafka-topics'
import { HEATMAPS_OUTPUT, PERSONS_OUTPUT, PERSON_DISTINCT_IDS_OUTPUT } from '../../analytics/outputs'
import {
    APP_METRICS_OUTPUT,
    DEFAULT_PRODUCER,
    DLQ_OUTPUT,
    GROUPS_OUTPUT,
    INGESTION_WARNINGS_OUTPUT,
    OVERFLOW_OUTPUT,
    type ProducerName,
} from '../../common/outputs'
import { IngestionOutputsBuilder } from '../../outputs/ingestion-outputs-builder'

export type HeatmapsOutputsConfig = {
    HEATMAPS_OUTPUT_HEATMAPS_TOPIC: string
    HEATMAPS_OUTPUT_HEATMAPS_PRODUCER: ProducerName
    HEATMAPS_OUTPUT_INGESTION_WARNINGS_TOPIC: string
    HEATMAPS_OUTPUT_INGESTION_WARNINGS_PRODUCER: ProducerName
    HEATMAPS_OUTPUT_DLQ_TOPIC: string
    HEATMAPS_OUTPUT_DLQ_PRODUCER: ProducerName
    HEATMAPS_OUTPUT_OVERFLOW_TOPIC: string
    HEATMAPS_OUTPUT_OVERFLOW_PRODUCER: ProducerName
    HEATMAPS_OUTPUT_GROUPS_TOPIC: string
    HEATMAPS_OUTPUT_GROUPS_PRODUCER: ProducerName
    HEATMAPS_OUTPUT_PERSONS_TOPIC: string
    HEATMAPS_OUTPUT_PERSONS_PRODUCER: ProducerName
    HEATMAPS_OUTPUT_PERSON_DISTINCT_IDS_TOPIC: string
    HEATMAPS_OUTPUT_PERSON_DISTINCT_IDS_PRODUCER: ProducerName
    HEATMAPS_OUTPUT_APP_METRICS_TOPIC: string
    HEATMAPS_OUTPUT_APP_METRICS_PRODUCER: ProducerName
}

export function getDefaultHeatmapsOutputsConfig(): HeatmapsOutputsConfig {
    return {
        HEATMAPS_OUTPUT_HEATMAPS_TOPIC: KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
        HEATMAPS_OUTPUT_HEATMAPS_PRODUCER: DEFAULT_PRODUCER,
        HEATMAPS_OUTPUT_INGESTION_WARNINGS_TOPIC: KAFKA_INGESTION_WARNINGS,
        HEATMAPS_OUTPUT_INGESTION_WARNINGS_PRODUCER: DEFAULT_PRODUCER,
        HEATMAPS_OUTPUT_DLQ_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
        HEATMAPS_OUTPUT_DLQ_PRODUCER: DEFAULT_PRODUCER,
        HEATMAPS_OUTPUT_OVERFLOW_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
        HEATMAPS_OUTPUT_OVERFLOW_PRODUCER: DEFAULT_PRODUCER,
        HEATMAPS_OUTPUT_GROUPS_TOPIC: KAFKA_GROUPS,
        HEATMAPS_OUTPUT_GROUPS_PRODUCER: DEFAULT_PRODUCER,
        HEATMAPS_OUTPUT_PERSONS_TOPIC: KAFKA_PERSON,
        HEATMAPS_OUTPUT_PERSONS_PRODUCER: DEFAULT_PRODUCER,
        HEATMAPS_OUTPUT_PERSON_DISTINCT_IDS_TOPIC: KAFKA_PERSON_DISTINCT_ID,
        HEATMAPS_OUTPUT_PERSON_DISTINCT_IDS_PRODUCER: DEFAULT_PRODUCER,
        HEATMAPS_OUTPUT_APP_METRICS_TOPIC: KAFKA_APP_METRICS_2,
        HEATMAPS_OUTPUT_APP_METRICS_PRODUCER: DEFAULT_PRODUCER,
    }
}

/**
 * Register the outputs the heatmaps pipeline writes to.
 *
 * Simple register (topic + producer) — no dual-write surface. Heatmaps is a
 * new consumer with no active migration, so the dual-write knobs would just
 * be cost-free env-var noise.
 *
 * Note: `OVERFLOW_OUTPUT` is registered because `applyEventRestrictions` types
 * its redirect arm as `'overflow'`; the heatmaps pipeline pins `overflowEnabled`
 * to false so nothing is ever written to it. The topic config still has to
 * resolve to satisfy the type check.
 */
export function registerHeatmapsOutputs() {
    return new IngestionOutputsBuilder()
        .register(HEATMAPS_OUTPUT, {
            topicKey: 'HEATMAPS_OUTPUT_HEATMAPS_TOPIC',
            producerKey: 'HEATMAPS_OUTPUT_HEATMAPS_PRODUCER',
        })
        .register(INGESTION_WARNINGS_OUTPUT, {
            topicKey: 'HEATMAPS_OUTPUT_INGESTION_WARNINGS_TOPIC',
            producerKey: 'HEATMAPS_OUTPUT_INGESTION_WARNINGS_PRODUCER',
        })
        .register(DLQ_OUTPUT, {
            topicKey: 'HEATMAPS_OUTPUT_DLQ_TOPIC',
            producerKey: 'HEATMAPS_OUTPUT_DLQ_PRODUCER',
        })
        .register(OVERFLOW_OUTPUT, {
            topicKey: 'HEATMAPS_OUTPUT_OVERFLOW_TOPIC',
            producerKey: 'HEATMAPS_OUTPUT_OVERFLOW_PRODUCER',
        })
        .register(GROUPS_OUTPUT, {
            topicKey: 'HEATMAPS_OUTPUT_GROUPS_TOPIC',
            producerKey: 'HEATMAPS_OUTPUT_GROUPS_PRODUCER',
        })
        .register(PERSONS_OUTPUT, {
            topicKey: 'HEATMAPS_OUTPUT_PERSONS_TOPIC',
            producerKey: 'HEATMAPS_OUTPUT_PERSONS_PRODUCER',
        })
        .register(PERSON_DISTINCT_IDS_OUTPUT, {
            topicKey: 'HEATMAPS_OUTPUT_PERSON_DISTINCT_IDS_TOPIC',
            producerKey: 'HEATMAPS_OUTPUT_PERSON_DISTINCT_IDS_PRODUCER',
        })
        .register(APP_METRICS_OUTPUT, {
            topicKey: 'HEATMAPS_OUTPUT_APP_METRICS_TOPIC',
            producerKey: 'HEATMAPS_OUTPUT_APP_METRICS_PRODUCER',
        })
}
