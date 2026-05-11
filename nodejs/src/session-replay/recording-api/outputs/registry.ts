import { IngestionOutputsBuilder } from '../../../ingestion/outputs/ingestion-outputs-builder'
import { REPLAY_EVENTS_OUTPUT, SESSION_FEATURES_OUTPUT } from '../../shared/outputs'

/** Register all recording-api outputs on the builder. Call `.build(registry, config)` to resolve. */
export function createOutputsRegistry() {
    return new IngestionOutputsBuilder()
        .register(REPLAY_EVENTS_OUTPUT, {
            topicKey: 'RECORDING_API_OUTPUT_REPLAY_EVENTS_TOPIC',
            producerKey: 'RECORDING_API_OUTPUT_REPLAY_EVENTS_PRODUCER',
        })
        .register(SESSION_FEATURES_OUTPUT, {
            topicKey: 'RECORDING_API_OUTPUT_SESSION_FEATURES_TOPIC',
            producerKey: 'RECORDING_API_OUTPUT_SESSION_FEATURES_PRODUCER',
        })
}
