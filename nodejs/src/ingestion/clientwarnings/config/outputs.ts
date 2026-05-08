import { KAFKA_EVENTS_PLUGIN_INGESTION_DLQ, KAFKA_INGESTION_WARNINGS } from '../../../config/kafka-topics'
import { DEFAULT_PRODUCER, DLQ_OUTPUT, INGESTION_WARNINGS_OUTPUT, type ProducerName } from '../../common/outputs'
import { IngestionOutputsBuilder } from '../../outputs/ingestion-outputs-builder'

export type ClientWarningsOutputsConfig = {
    CLIENT_WARNINGS_OUTPUT_INGESTION_WARNINGS_TOPIC: string
    CLIENT_WARNINGS_OUTPUT_INGESTION_WARNINGS_PRODUCER: ProducerName
    CLIENT_WARNINGS_OUTPUT_DLQ_TOPIC: string
    CLIENT_WARNINGS_OUTPUT_DLQ_PRODUCER: ProducerName
}

export function getDefaultClientWarningsOutputsConfig(): ClientWarningsOutputsConfig {
    return {
        CLIENT_WARNINGS_OUTPUT_INGESTION_WARNINGS_TOPIC: KAFKA_INGESTION_WARNINGS,
        CLIENT_WARNINGS_OUTPUT_INGESTION_WARNINGS_PRODUCER: DEFAULT_PRODUCER,
        CLIENT_WARNINGS_OUTPUT_DLQ_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
        CLIENT_WARNINGS_OUTPUT_DLQ_PRODUCER: DEFAULT_PRODUCER,
    }
}

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
