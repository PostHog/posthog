import {
    AI_EVENTS_OUTPUT,
    APP_METRICS_OUTPUT,
    DLQ_OUTPUT,
    EVENTS_OUTPUT,
    INGESTION_WARNINGS_OUTPUT,
    LOG_ENTRIES_OUTPUT,
    OVERFLOW_OUTPUT,
    TOPHOG_OUTPUT,
} from '~/common/outputs'
import { IngestionOutputsBuilder } from '~/common/outputs/ingestion-outputs-builder'

/**
 * Register the outputs the AI pipeline produces to. Like the analytics AI
 * branch, AI events are double-written to both the events output (main events
 * table) and the dedicated ai_events output. No persons/groups outputs — the
 * AI pipeline reads person/group data but never writes it. app_metrics +
 * log_entries back the hog-function monitoring path (the transformer runs in
 * this lane). Call `.build(registry, config)` to resolve against the shared
 * producer registry.
 */
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
