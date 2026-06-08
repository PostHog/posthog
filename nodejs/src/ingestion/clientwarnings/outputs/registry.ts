import { APP_METRICS_OUTPUT, DLQ_OUTPUT, INGESTION_WARNINGS_OUTPUT } from '../../common/outputs'
import { IngestionOutputsBuilder } from '../../outputs/ingestion-outputs-builder'

/**
 * Register the outputs the clientwarnings pipeline produces to. Call
 * `.build(registry, config)` to resolve against the shared producer
 * registry.
 */
export function createOutputsRegistry() {
    return new IngestionOutputsBuilder()
        .registerDualWrite(INGESTION_WARNINGS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_INGESTION_WARNINGS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_INGESTION_WARNINGS_PRODUCER',
            secondaryTopicKey: 'INGESTION_OUTPUT_INGESTION_WARNINGS_SECONDARY_TOPIC',
            secondaryProducerKey: 'INGESTION_OUTPUT_INGESTION_WARNINGS_SECONDARY_PRODUCER',
            modeKey: 'INGESTION_OUTPUT_INGESTION_WARNINGS_SECONDARY_MODE',
            percentageKey: 'INGESTION_OUTPUT_INGESTION_WARNINGS_SECONDARY_PERCENTAGE',
        })
        .registerDualWrite(DLQ_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_DLQ_TOPIC',
            producerKey: 'INGESTION_OUTPUT_DLQ_PRODUCER',
            secondaryTopicKey: 'INGESTION_OUTPUT_DLQ_SECONDARY_TOPIC',
            secondaryProducerKey: 'INGESTION_OUTPUT_DLQ_SECONDARY_PRODUCER',
            modeKey: 'INGESTION_OUTPUT_DLQ_SECONDARY_MODE',
            percentageKey: 'INGESTION_OUTPUT_DLQ_SECONDARY_PERCENTAGE',
        })
        .registerDualWriteWithDenylist(APP_METRICS_OUTPUT, {
            topicKey: 'INGESTION_OUTPUT_APP_METRICS_TOPIC',
            producerKey: 'INGESTION_OUTPUT_APP_METRICS_PRODUCER',
            secondaryTopicKey: 'INGESTION_OUTPUT_APP_METRICS_SECONDARY_TOPIC',
            secondaryProducerKey: 'INGESTION_OUTPUT_APP_METRICS_SECONDARY_PRODUCER',
            modeKey: 'INGESTION_OUTPUT_APP_METRICS_SECONDARY_MODE',
            percentageKey: 'INGESTION_OUTPUT_APP_METRICS_SECONDARY_PERCENTAGE',
            teamDenylistKey: 'INGESTION_OUTPUT_APP_METRICS_SECONDARY_TEAM_DENYLIST',
        })
}
