import {
    KAFKA_APP_METRICS_2,
    KAFKA_CLICKHOUSE_TOPHOG,
    KAFKA_ERROR_TRACKING_INGESTION_DLQ,
    KAFKA_ERROR_TRACKING_INGESTION_OVERFLOW,
    KAFKA_EVENTS_JSON,
    KAFKA_INGESTION_WARNINGS,
    KAFKA_LOG_ENTRIES,
} from '../../../config/kafka-topics'
import {
    APP_METRICS_OUTPUT,
    DLQ_OUTPUT,
    EVENTS_OUTPUT,
    INGESTION_WARNINGS_OUTPUT,
    LOG_ENTRIES_OUTPUT,
    OVERFLOW_OUTPUT,
    TOPHOG_OUTPUT,
} from '../../common/outputs'
import { IngestionOutputDefinition } from '../../outputs/resolver'
import { DEFAULT_PRODUCER, ProducerName } from './producers'

/** Static config for all error tracking ingestion outputs. */
export const ERROR_TRACKING_OUTPUT_DEFINITIONS: Record<string, IngestionOutputDefinition<ProducerName>> = {
    [EVENTS_OUTPUT]: {
        defaultTopic: KAFKA_EVENTS_JSON,
        defaultProducerName: DEFAULT_PRODUCER,
        producerOverrideEnvVar: 'ERROR_TRACKING_OUTPUT_EVENTS_PRODUCER',
        topicOverrideEnvVar: 'ERROR_TRACKING_CONSUMER_OUTPUT_TOPIC',
    },
    [INGESTION_WARNINGS_OUTPUT]: {
        defaultTopic: KAFKA_INGESTION_WARNINGS,
        defaultProducerName: DEFAULT_PRODUCER,
        producerOverrideEnvVar: 'ERROR_TRACKING_OUTPUT_INGESTION_WARNINGS_PRODUCER',
        topicOverrideEnvVar: 'ERROR_TRACKING_OUTPUT_INGESTION_WARNINGS_TOPIC',
    },
    [DLQ_OUTPUT]: {
        defaultTopic: KAFKA_ERROR_TRACKING_INGESTION_DLQ,
        defaultProducerName: DEFAULT_PRODUCER,
        producerOverrideEnvVar: 'ERROR_TRACKING_OUTPUT_DLQ_PRODUCER',
        topicOverrideEnvVar: 'ERROR_TRACKING_CONSUMER_DLQ_TOPIC',
    },
    [OVERFLOW_OUTPUT]: {
        defaultTopic: KAFKA_ERROR_TRACKING_INGESTION_OVERFLOW,
        defaultProducerName: DEFAULT_PRODUCER,
        producerOverrideEnvVar: 'ERROR_TRACKING_OUTPUT_OVERFLOW_PRODUCER',
        topicOverrideEnvVar: 'ERROR_TRACKING_CONSUMER_OVERFLOW_TOPIC',
    },
    [APP_METRICS_OUTPUT]: {
        defaultTopic: KAFKA_APP_METRICS_2,
        defaultProducerName: DEFAULT_PRODUCER,
        producerOverrideEnvVar: 'ERROR_TRACKING_OUTPUT_APP_METRICS_PRODUCER',
        topicOverrideEnvVar: 'ERROR_TRACKING_OUTPUT_APP_METRICS_TOPIC',
    },
    [LOG_ENTRIES_OUTPUT]: {
        defaultTopic: KAFKA_LOG_ENTRIES,
        defaultProducerName: DEFAULT_PRODUCER,
        producerOverrideEnvVar: 'ERROR_TRACKING_OUTPUT_LOG_ENTRIES_PRODUCER',
        topicOverrideEnvVar: 'ERROR_TRACKING_OUTPUT_LOG_ENTRIES_TOPIC',
    },
    [TOPHOG_OUTPUT]: {
        defaultTopic: KAFKA_CLICKHOUSE_TOPHOG,
        defaultProducerName: DEFAULT_PRODUCER,
        producerOverrideEnvVar: 'ERROR_TRACKING_OUTPUT_TOPHOG_PRODUCER',
        topicOverrideEnvVar: 'ERROR_TRACKING_OUTPUT_TOPHOG_TOPIC',
    },
}
