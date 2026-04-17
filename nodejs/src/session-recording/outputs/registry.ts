import {
    DLQ_OUTPUT,
    INGESTION_WARNINGS_OUTPUT,
    LOG_ENTRIES_OUTPUT,
    OVERFLOW_OUTPUT,
    TOPHOG_OUTPUT,
} from '../../ingestion/common/outputs'
import { IngestionOutputsBuilder } from '../../ingestion/outputs/ingestion-outputs-builder'

/** Register all session replay outputs on the builder. Call `.build(registry, config)` to resolve. */
export function createOutputsRegistry() {
    return new IngestionOutputsBuilder()
        .register(INGESTION_WARNINGS_OUTPUT, {
            topicKey: 'SESSION_REPLAY_OUTPUT_INGESTION_WARNINGS_TOPIC',
            producerKey: 'SESSION_REPLAY_OUTPUT_INGESTION_WARNINGS_PRODUCER',
        })
        .register(DLQ_OUTPUT, {
            topicKey: 'INGESTION_SESSION_REPLAY_CONSUMER_DLQ_TOPIC',
            producerKey: 'SESSION_REPLAY_OUTPUT_DLQ_PRODUCER',
        })
        .register(OVERFLOW_OUTPUT, {
            topicKey: 'INGESTION_SESSION_REPLAY_CONSUMER_OVERFLOW_TOPIC',
            producerKey: 'SESSION_REPLAY_OUTPUT_OVERFLOW_PRODUCER',
        })
        .register(TOPHOG_OUTPUT, {
            topicKey: 'SESSION_REPLAY_OUTPUT_TOPHOG_TOPIC',
            producerKey: 'SESSION_REPLAY_OUTPUT_TOPHOG_PRODUCER',
        })
        .register(LOG_ENTRIES_OUTPUT, {
            topicKey: 'SESSION_RECORDING_V2_CONSOLE_LOG_ENTRIES_KAFKA_TOPIC',
            producerKey: 'SESSION_REPLAY_OUTPUT_LOG_ENTRIES_PRODUCER',
        })
}
