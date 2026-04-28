import { REPLAY_EVENTS_OUTPUT, SESSION_FEATURES_OUTPUT } from '../../../ingestion/common/outputs'
import { IngestionOutputsBuilder } from '../../../ingestion/outputs/ingestion-outputs-builder'

/** Register all recording-api outputs on the builder. Call `.build(registry, config)` to resolve. */
export function createOutputsRegistry() {
    return new IngestionOutputsBuilder()
        .register(REPLAY_EVENTS_OUTPUT, {
            topicKey: 'SESSION_RECORDING_V2_REPLAY_EVENTS_KAFKA_TOPIC',
            producerKey: 'SESSION_REPLAY_OUTPUT_REPLAY_EVENTS_PRODUCER',
        })
        .register(SESSION_FEATURES_OUTPUT, {
            topicKey: 'SESSION_RECORDING_V2_SESSION_FEATURES_KAFKA_TOPIC',
            producerKey: 'SESSION_REPLAY_OUTPUT_SESSION_FEATURES_PRODUCER',
        })
}
