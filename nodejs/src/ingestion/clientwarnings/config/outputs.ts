import { DLQ_OUTPUT, INGESTION_WARNINGS_OUTPUT } from '../../common/outputs'
import { IngestionOutputsBuilder } from '../../outputs/ingestion-outputs-builder'

export function registerClientWarningsOutputs() {
    return new IngestionOutputsBuilder()
        .register(INGESTION_WARNINGS_OUTPUT, {
            topicKey: 'CLIENT_WARNINGS_OUTPUT_INGESTION_WARNINGS_TOPIC',
            producerKey: 'CLIENT_WARNINGS_OUTPUT_INGESTION_WARNINGS_PRODUCER',
        })
        .register(DLQ_OUTPUT, {
            topicKey: 'CLIENT_WARNINGS_OUTPUT_DLQ_TOPIC',
            producerKey: 'CLIENT_WARNINGS_OUTPUT_DLQ_PRODUCER',
        })
}
