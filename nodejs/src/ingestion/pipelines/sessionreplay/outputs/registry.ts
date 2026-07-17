import {
    DLQ_OUTPUT,
    INGESTION_WARNINGS_OUTPUT,
    LOG_ENTRIES_OUTPUT,
    OVERFLOW_OUTPUT,
    TOPHOG_OUTPUT,
} from '~/common/outputs'
import { IngestionOutputsBuilder } from '~/common/outputs/ingestion-outputs-builder'
import {
    ML_BLOCK_METADATA_OUTPUT,
    REPLAY_EVENTS_OUTPUT,
    SESSION_FEATURES_OUTPUT,
} from '~/ingestion/pipelines/sessionreplay/shared/outputs'

/** Register all session replay outputs on the builder. Call `.build(registry, config)` to resolve. */
export function createOutputsRegistry() {
    return new IngestionOutputsBuilder()
        .register(INGESTION_WARNINGS_OUTPUT, {
            topicKey: 'INGESTION_SESSIONREPLAY_OUTPUT_INGESTION_WARNINGS_TOPIC',
            producerKey: 'INGESTION_SESSIONREPLAY_OUTPUT_INGESTION_WARNINGS_PRODUCER',
        })
        .register(DLQ_OUTPUT, {
            topicKey: 'INGESTION_SESSIONREPLAY_OUTPUT_DLQ_TOPIC',
            producerKey: 'INGESTION_SESSIONREPLAY_OUTPUT_DLQ_PRODUCER',
        })
        .register(OVERFLOW_OUTPUT, {
            topicKey: 'INGESTION_SESSIONREPLAY_OUTPUT_OVERFLOW_TOPIC',
            producerKey: 'INGESTION_SESSIONREPLAY_OUTPUT_OVERFLOW_PRODUCER',
        })
        .register(TOPHOG_OUTPUT, {
            topicKey: 'INGESTION_SESSIONREPLAY_OUTPUT_TOPHOG_TOPIC',
            producerKey: 'INGESTION_SESSIONREPLAY_OUTPUT_TOPHOG_PRODUCER',
        })
        .register(LOG_ENTRIES_OUTPUT, {
            topicKey: 'INGESTION_SESSIONREPLAY_OUTPUT_LOG_ENTRIES_TOPIC',
            producerKey: 'INGESTION_SESSIONREPLAY_OUTPUT_LOG_ENTRIES_PRODUCER',
        })
        .register(REPLAY_EVENTS_OUTPUT, {
            topicKey: 'INGESTION_SESSIONREPLAY_OUTPUT_REPLAY_EVENTS_TOPIC',
            producerKey: 'INGESTION_SESSIONREPLAY_OUTPUT_REPLAY_EVENTS_PRODUCER',
        })
        .register(SESSION_FEATURES_OUTPUT, {
            topicKey: 'INGESTION_SESSIONREPLAY_OUTPUT_SESSION_FEATURES_TOPIC',
            producerKey: 'INGESTION_SESSIONREPLAY_OUTPUT_SESSION_FEATURES_PRODUCER',
        })
        .register(ML_BLOCK_METADATA_OUTPUT, {
            topicKey: 'INGESTION_SESSIONREPLAY_OUTPUT_ML_BLOCK_METADATA_TOPIC',
            producerKey: 'INGESTION_SESSIONREPLAY_OUTPUT_ML_BLOCK_METADATA_PRODUCER',
        })
}
