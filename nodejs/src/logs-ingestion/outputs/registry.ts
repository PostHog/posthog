import { APP_METRICS_OUTPUT } from '../../ingestion/common/outputs'
import { IngestionOutputsBuilder } from '../../ingestion/outputs/ingestion-outputs-builder'

/** Register all logs/traces ingestion outputs on the builder. Call `.build(registry, config)` to resolve. */
export function createOutputsRegistry() {
    return new IngestionOutputsBuilder().register(APP_METRICS_OUTPUT, {
        topicKey: 'LOGS_INGESTION_OUTPUT_APP_METRICS_TOPIC',
        producerKey: 'LOGS_INGESTION_OUTPUT_APP_METRICS_PRODUCER',
    })
}
