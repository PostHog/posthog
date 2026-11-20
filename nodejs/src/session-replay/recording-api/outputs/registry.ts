import { IngestionOutputsBuilder } from '~/common/outputs/ingestion-outputs-builder'
import { REPLAY_EVENTS_OUTPUT } from '~/ingestion/pipelines/sessionreplay/shared/outputs'

/** Register all recording-api outputs on the builder. Call `.build(registry, config)` to resolve. */
export function createOutputsRegistry() {
    return new IngestionOutputsBuilder().register(REPLAY_EVENTS_OUTPUT, {
        topicKey: 'RECORDING_API_OUTPUT_REPLAY_EVENTS_TOPIC',
        producerKey: 'RECORDING_API_OUTPUT_REPLAY_EVENTS_PRODUCER',
    })
}
