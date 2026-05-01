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
import { SingleIngestionOutput } from '../../src/ingestion/outputs/single-ingestion-output'
import { KafkaProducerWrapper } from '../../src/kafka/producer'

function testOutput(name: string, topic: string, producer: KafkaProducerWrapper): SingleIngestionOutput {
    return new SingleIngestionOutput(name, topic, producer, 'test')
}

export function createTestMonitoringOutputs(kafkaProducer: KafkaProducerWrapper) {
    return new IngestionOutputs({
        [APP_METRICS_OUTPUT]: testOutput(APP_METRICS_OUTPUT, KAFKA_APP_METRICS_2, kafkaProducer),
        [LOG_ENTRIES_OUTPUT]: testOutput(LOG_ENTRIES_OUTPUT, KAFKA_LOG_ENTRIES, kafkaProducer),
    })
}

export function createTestIngestionOutputs(kafkaProducer: KafkaProducerWrapper) {
    return new IngestionOutputs({
        [EVENTS_OUTPUT]: testOutput(EVENTS_OUTPUT, KAFKA_EVENTS_JSON, kafkaProducer),
        [AI_EVENTS_OUTPUT]: testOutput(AI_EVENTS_OUTPUT, KAFKA_CLICKHOUSE_AI_EVENTS_JSON, kafkaProducer),
        [HEATMAPS_OUTPUT]: testOutput(HEATMAPS_OUTPUT, KAFKA_CLICKHOUSE_HEATMAP_EVENTS, kafkaProducer),
        [INGESTION_WARNINGS_OUTPUT]: testOutput(INGESTION_WARNINGS_OUTPUT, KAFKA_INGESTION_WARNINGS, kafkaProducer),
        [DLQ_OUTPUT]: testOutput(DLQ_OUTPUT, KAFKA_EVENTS_PLUGIN_INGESTION_DLQ, kafkaProducer),
        [OVERFLOW_OUTPUT]: testOutput(OVERFLOW_OUTPUT, KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW, kafkaProducer),
        [ASYNC_OUTPUT]: testOutput(ASYNC_OUTPUT, KAFKA_EVENTS_PLUGIN_INGESTION_ASYNC, kafkaProducer),
        [GROUPS_OUTPUT]: testOutput(GROUPS_OUTPUT, KAFKA_GROUPS, kafkaProducer),
        [PERSONS_OUTPUT]: testOutput(PERSONS_OUTPUT, KAFKA_PERSON, kafkaProducer),
        [PERSON_DISTINCT_IDS_OUTPUT]: testOutput(PERSON_DISTINCT_IDS_OUTPUT, KAFKA_PERSON_DISTINCT_ID, kafkaProducer),
        [APP_METRICS_OUTPUT]: testOutput(APP_METRICS_OUTPUT, KAFKA_APP_METRICS_2, kafkaProducer),
        [LOG_ENTRIES_OUTPUT]: testOutput(LOG_ENTRIES_OUTPUT, KAFKA_LOG_ENTRIES, kafkaProducer),
        [TOPHOG_OUTPUT]: testOutput(TOPHOG_OUTPUT, KAFKA_CLICKHOUSE_TOPHOG, kafkaProducer),
    })
}
