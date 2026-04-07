import {
    KAFKA_APP_METRICS_2,
    KAFKA_CLICKHOUSE_AI_EVENTS_JSON,
    KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
    KAFKA_CLICKHOUSE_TOPHOG,
    KAFKA_EVENTS_JSON,
    KAFKA_EVENTS_PLUGIN_INGESTION_ASYNC,
    KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
    KAFKA_GROUPS,
    KAFKA_INGESTION_WARNINGS,
    KAFKA_LOG_ENTRIES,
    KAFKA_PERSON,
    KAFKA_PERSON_DISTINCT_ID,
} from '../../src/config/kafka-topics'
import {
    AI_EVENTS_OUTPUT,
    ASYNC_OUTPUT,
    EVENTS_OUTPUT,
    HEATMAPS_OUTPUT,
    PERSONS_OUTPUT,
    PERSON_DISTINCT_IDS_OUTPUT,
} from '../../src/ingestion/analytics/outputs'
import {
    APP_METRICS_OUTPUT,
    DLQ_OUTPUT,
    GROUPS_OUTPUT,
    INGESTION_WARNINGS_OUTPUT,
    LOG_ENTRIES_OUTPUT,
    OVERFLOW_OUTPUT,
    TOPHOG_OUTPUT,
} from '../../src/ingestion/common/outputs'
import { IngestionOutputs } from '../../src/ingestion/outputs/ingestion-outputs'
import { KafkaProducerWrapper } from '../../src/kafka/producer'

export function createTestMonitoringOutputs(kafkaProducer: KafkaProducerWrapper) {
    return new IngestionOutputs({
        [APP_METRICS_OUTPUT]: [{ topic: KAFKA_APP_METRICS_2, producer: kafkaProducer, producerName: 'test' }],
        [LOG_ENTRIES_OUTPUT]: [{ topic: KAFKA_LOG_ENTRIES, producer: kafkaProducer, producerName: 'test' }],
    })
}

export function createTestIngestionOutputs(kafkaProducer: KafkaProducerWrapper) {
    return new IngestionOutputs({
        [EVENTS_OUTPUT]: [{ topic: KAFKA_EVENTS_JSON, producer: kafkaProducer, producerName: 'test' }],
        [AI_EVENTS_OUTPUT]: [{ topic: KAFKA_CLICKHOUSE_AI_EVENTS_JSON, producer: kafkaProducer, producerName: 'test' }],
        [HEATMAPS_OUTPUT]: [{ topic: KAFKA_CLICKHOUSE_HEATMAP_EVENTS, producer: kafkaProducer, producerName: 'test' }],
        [INGESTION_WARNINGS_OUTPUT]: [
            { topic: KAFKA_INGESTION_WARNINGS, producer: kafkaProducer, producerName: 'test' },
        ],
        [DLQ_OUTPUT]: [{ topic: KAFKA_EVENTS_PLUGIN_INGESTION_DLQ, producer: kafkaProducer, producerName: 'test' }],
        [OVERFLOW_OUTPUT]: [
            { topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW, producer: kafkaProducer, producerName: 'test' },
        ],
        [ASYNC_OUTPUT]: [{ topic: KAFKA_EVENTS_PLUGIN_INGESTION_ASYNC, producer: kafkaProducer, producerName: 'test' }],
        [GROUPS_OUTPUT]: [{ topic: KAFKA_GROUPS, producer: kafkaProducer, producerName: 'test' }],
        [PERSONS_OUTPUT]: [{ topic: KAFKA_PERSON, producer: kafkaProducer, producerName: 'test' }],
        [PERSON_DISTINCT_IDS_OUTPUT]: [
            { topic: KAFKA_PERSON_DISTINCT_ID, producer: kafkaProducer, producerName: 'test' },
        ],
        [APP_METRICS_OUTPUT]: [{ topic: KAFKA_APP_METRICS_2, producer: kafkaProducer, producerName: 'test' }],
        [LOG_ENTRIES_OUTPUT]: [{ topic: KAFKA_LOG_ENTRIES, producer: kafkaProducer, producerName: 'test' }],
        [TOPHOG_OUTPUT]: [{ topic: KAFKA_CLICKHOUSE_TOPHOG, producer: kafkaProducer, producerName: 'test' }],
    })
}
