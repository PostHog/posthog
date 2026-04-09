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
        .registerDualWrite(EVENTS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_EVENTS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_EVENTS_PRODUCER',
            secondaryTopicKey: 'INGESTION_OUTPUT_EVENTS_SECONDARY_TOPIC',
            secondaryProducerKey: 'INGESTION_OUTPUT_EVENTS_SECONDARY_PRODUCER',
        })
        .registerDualWrite(AI_EVENTS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_AI_EVENTS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_AI_EVENTS_PRODUCER',
            secondaryTopicKey: 'INGESTION_OUTPUT_AI_EVENTS_SECONDARY_TOPIC',
            secondaryProducerKey: 'INGESTION_OUTPUT_AI_EVENTS_SECONDARY_PRODUCER',
        })
        .registerDualWrite(HEATMAPS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_HEATMAPS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_HEATMAPS_PRODUCER',
            secondaryTopicKey: 'INGESTION_OUTPUT_HEATMAPS_SECONDARY_TOPIC',
            secondaryProducerKey: 'INGESTION_OUTPUT_HEATMAPS_SECONDARY_PRODUCER',
        })
        .registerDualWrite(INGESTION_WARNINGS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_INGESTION_WARNINGS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_INGESTION_WARNINGS_PRODUCER',
            secondaryTopicKey: 'INGESTION_OUTPUT_INGESTION_WARNINGS_SECONDARY_TOPIC',
            secondaryProducerKey: 'INGESTION_OUTPUT_INGESTION_WARNINGS_SECONDARY_PRODUCER',
        })
        .registerDualWrite(DLQ_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_DLQ_TOPIC',
            producerKey: 'INGESTION_OUTPUT_DLQ_PRODUCER',
            secondaryTopicKey: 'INGESTION_OUTPUT_DLQ_SECONDARY_TOPIC',
            secondaryProducerKey: 'INGESTION_OUTPUT_DLQ_SECONDARY_PRODUCER',
        })
        .registerDualWrite(OVERFLOW_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_OVERFLOW_TOPIC',
            producerKey: 'INGESTION_OUTPUT_OVERFLOW_PRODUCER',
            secondaryTopicKey: 'INGESTION_OUTPUT_OVERFLOW_SECONDARY_TOPIC',
            secondaryProducerKey: 'INGESTION_OUTPUT_OVERFLOW_SECONDARY_PRODUCER',
        })
        .registerDualWrite(ASYNC_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_ASYNC_TOPIC',
            producerKey: 'INGESTION_OUTPUT_ASYNC_PRODUCER',
            secondaryTopicKey: 'INGESTION_OUTPUT_ASYNC_SECONDARY_TOPIC',
            secondaryProducerKey: 'INGESTION_OUTPUT_ASYNC_SECONDARY_PRODUCER',
        })
        .registerDualWrite(GROUPS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_GROUPS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_GROUPS_PRODUCER',
            secondaryTopicKey: 'INGESTION_OUTPUT_GROUPS_SECONDARY_TOPIC',
            secondaryProducerKey: 'INGESTION_OUTPUT_GROUPS_SECONDARY_PRODUCER',
        })
        .registerDualWrite(PERSONS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_PERSONS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_PERSONS_PRODUCER',
            secondaryTopicKey: 'INGESTION_OUTPUT_PERSONS_SECONDARY_TOPIC',
            secondaryProducerKey: 'INGESTION_OUTPUT_PERSONS_SECONDARY_PRODUCER',
        })
        .registerDualWrite(PERSON_DISTINCT_IDS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_PERSON_DISTINCT_IDS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_PERSON_DISTINCT_IDS_PRODUCER',
            secondaryTopicKey: 'INGESTION_OUTPUT_PERSON_DISTINCT_IDS_SECONDARY_TOPIC',
            secondaryProducerKey: 'INGESTION_OUTPUT_PERSON_DISTINCT_IDS_SECONDARY_PRODUCER',
        })
        .registerDualWrite(APP_METRICS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_APP_METRICS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_APP_METRICS_PRODUCER',
            secondaryTopicKey: 'INGESTION_OUTPUT_APP_METRICS_SECONDARY_TOPIC',
            secondaryProducerKey: 'INGESTION_OUTPUT_APP_METRICS_SECONDARY_PRODUCER',
        })
        .registerDualWrite(LOG_ENTRIES_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_LOG_ENTRIES_TOPIC',
            producerKey: 'INGESTION_OUTPUT_LOG_ENTRIES_PRODUCER',
            secondaryTopicKey: 'INGESTION_OUTPUT_LOG_ENTRIES_SECONDARY_TOPIC',
            secondaryProducerKey: 'INGESTION_OUTPUT_LOG_ENTRIES_SECONDARY_PRODUCER',
        })
        .registerDualWrite(TOPHOG_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_TOPHOG_TOPIC',
            producerKey: 'INGESTION_OUTPUT_TOPHOG_PRODUCER',
            secondaryTopicKey: 'INGESTION_OUTPUT_TOPHOG_SECONDARY_TOPIC',
            secondaryProducerKey: 'INGESTION_OUTPUT_TOPHOG_SECONDARY_PRODUCER',
        })
}
