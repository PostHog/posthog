import {
    AI_EVENTS_OUTPUT,
    ASYNC_OUTPUT,
    EVENTS_OUTPUT,
    HEATMAPS_OUTPUT,
    PERSONS_OUTPUT,
    PERSON_DISTINCT_IDS_OUTPUT,
} from '.'

import {
    APP_METRICS_OUTPUT,
    DLQ_OUTPUT,
    GROUPS_OUTPUT,
    INGESTION_WARNINGS_OUTPUT,
    LOG_ENTRIES_OUTPUT,
    OVERFLOW_OUTPUT,
    TOPHOG_OUTPUT,
} from '../../common/outputs'
import { IngestionOutputsBuilder } from '../../outputs/ingestion-outputs-builder'

/** Register all analytics ingestion outputs on the builder. Call `.build(registry, config)` to resolve. */
export function createOutputsRegistry() {
    return new IngestionOutputsBuilder()
        .register(EVENTS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_EVENTS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_EVENTS_PRODUCER',
        })
        .register(AI_EVENTS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_AI_EVENTS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_AI_EVENTS_PRODUCER',
        })
        .register(HEATMAPS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_HEATMAPS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_HEATMAPS_PRODUCER',
        })
        .register(INGESTION_WARNINGS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_INGESTION_WARNINGS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_INGESTION_WARNINGS_PRODUCER',
        })
        .register(DLQ_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_DLQ_TOPIC',
            producerKey: 'INGESTION_OUTPUT_DLQ_PRODUCER',
        })
        .register(OVERFLOW_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_OVERFLOW_TOPIC',
            producerKey: 'INGESTION_OUTPUT_OVERFLOW_PRODUCER',
        })
        .register(ASYNC_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_ASYNC_TOPIC',
            producerKey: 'INGESTION_OUTPUT_ASYNC_PRODUCER',
        })
        .register(GROUPS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_GROUPS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_GROUPS_PRODUCER',
        })
        .register(PERSONS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_PERSONS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_PERSONS_PRODUCER',
        })
        .register(PERSON_DISTINCT_IDS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_PERSON_DISTINCT_IDS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_PERSON_DISTINCT_IDS_PRODUCER',
        })
        .register(APP_METRICS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_APP_METRICS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_APP_METRICS_PRODUCER',
        })
        .register(LOG_ENTRIES_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_LOG_ENTRIES_TOPIC',
            producerKey: 'INGESTION_OUTPUT_LOG_ENTRIES_PRODUCER',
        })
        .register(TOPHOG_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_TOPHOG_TOPIC',
            producerKey: 'INGESTION_OUTPUT_TOPHOG_PRODUCER',
        })
}
