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
    KAFKA_PERSON_MERGE_EVENTS,
} from '~/common/config/kafka-topics'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import {
    APP_METRICS_OUTPUT,
    DLQ_OUTPUT,
    GROUPS_OUTPUT,
    INGESTION_WARNINGS_OUTPUT,
    LOG_ENTRIES_OUTPUT,
    OVERFLOW_OUTPUT,
    TOPHOG_OUTPUT,
} from '~/common/outputs'
import {
    AI_EVENTS_OUTPUT,
    ASYNC_OUTPUT,
    EVENTS_OUTPUT,
    PERSONS_OUTPUT,
    PERSON_DISTINCT_IDS_OUTPUT,
    PERSON_MERGE_EVENTS_OUTPUT,
} from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { SingleIngestionOutput } from '~/common/outputs/single-ingestion-output'
import { HEATMAPS_OUTPUT } from '~/ingestion/pipelines/heatmaps/outputs'

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
        [PERSON_MERGE_EVENTS_OUTPUT]: testOutput(PERSON_MERGE_EVENTS_OUTPUT, KAFKA_PERSON_MERGE_EVENTS, kafkaProducer),
        [APP_METRICS_OUTPUT]: testOutput(APP_METRICS_OUTPUT, KAFKA_APP_METRICS_2, kafkaProducer),
        [LOG_ENTRIES_OUTPUT]: testOutput(LOG_ENTRIES_OUTPUT, KAFKA_LOG_ENTRIES, kafkaProducer),
        [TOPHOG_OUTPUT]: testOutput(TOPHOG_OUTPUT, KAFKA_CLICKHOUSE_TOPHOG, kafkaProducer),
    })
}
