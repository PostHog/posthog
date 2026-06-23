import { APP_METRICS_OUTPUT, DLQ_OUTPUT, INGESTION_WARNINGS_OUTPUT } from '~/common/outputs'
import { IngestionOutputsBuilder } from '~/common/outputs/ingestion-outputs-builder'

/**
 * Register the outputs the clientwarnings pipeline produces to. Call
 * `.build(registry, config)` to resolve against the shared producer
 * registry.
 */
export function createOutputsRegistry() {
    return new IngestionOutputsBuilder()
        .register(INGESTION_WARNINGS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_INGESTION_WARNINGS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_INGESTION_WARNINGS_PRODUCER',
        })
        .register(DLQ_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_DLQ_TOPIC',
            producerKey: 'INGESTION_OUTPUT_DLQ_PRODUCER',
        })
        .register(APP_METRICS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_APP_METRICS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_APP_METRICS_PRODUCER',
        })
}
