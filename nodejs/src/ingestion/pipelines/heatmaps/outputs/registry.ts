import { APP_METRICS_OUTPUT, DLQ_OUTPUT, INGESTION_WARNINGS_OUTPUT } from '~/common/outputs'
import { IngestionOutputsBuilder } from '~/common/outputs/ingestion-outputs-builder'

import { HEATMAPS_OUTPUT } from './index'

/**
 * Register the outputs the heatmaps pipeline produces to. Call
 * `.build(registry, config)` to resolve against the shared producer
 * registry.
 */
export function createOutputsRegistry() {
    return new IngestionOutputsBuilder()
        .register(HEATMAPS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_HEATMAPS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_HEATMAPS_PRODUCER',
        })
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
