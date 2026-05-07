import {
    AI_EVENTS_OUTPUT,
    ASYNC_OUTPUT,
    EVENTS_OUTPUT,
    PERSONS_OUTPUT,
    PERSON_DISTINCT_IDS_OUTPUT,
} from '../../analytics/outputs'
import {
    APP_METRICS_OUTPUT,
    DLQ_OUTPUT,
    GROUPS_OUTPUT,
    INGESTION_WARNINGS_OUTPUT,
    OVERFLOW_OUTPUT,
    TOPHOG_OUTPUT,
} from '../../common/outputs'
import { IngestionOutputsBuilder } from '../../outputs/ingestion-outputs-builder'

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
