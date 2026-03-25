import {
    KAFKA_CLICKHOUSE_AI_EVENTS_JSON,
    KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
    KAFKA_EVENTS_JSON,
    KAFKA_INGESTION_WARNINGS,
} from '../../src/config/kafka-topics'
import { AI_EVENTS_OUTPUT, EVENTS_OUTPUT, HEATMAPS_OUTPUT } from '../../src/ingestion/analytics/outputs'
import { INGESTION_WARNINGS_OUTPUT } from '../../src/ingestion/common/outputs'
import { IngestionOutputs } from '../../src/ingestion/outputs/ingestion-outputs'
import { KafkaProducerWrapper } from '../../src/kafka/producer'

export function createTestIngestionOutputs(kafkaProducer: KafkaProducerWrapper) {
    return new IngestionOutputs({
        [EVENTS_OUTPUT]: { topic: KAFKA_EVENTS_JSON, producer: kafkaProducer },
        [AI_EVENTS_OUTPUT]: { topic: KAFKA_CLICKHOUSE_AI_EVENTS_JSON, producer: kafkaProducer },
        [HEATMAPS_OUTPUT]: { topic: KAFKA_CLICKHOUSE_HEATMAP_EVENTS, producer: kafkaProducer },
        [INGESTION_WARNINGS_OUTPUT]: { topic: KAFKA_INGESTION_WARNINGS, producer: kafkaProducer },
    })
}
