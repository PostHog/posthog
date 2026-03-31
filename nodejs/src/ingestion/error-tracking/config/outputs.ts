import {
    KAFKA_ERROR_TRACKING_INGESTION_DLQ,
    KAFKA_ERROR_TRACKING_INGESTION_OVERFLOW,
    KAFKA_EVENTS_JSON,
    KAFKA_INGESTION_WARNINGS,
} from '../../../config/kafka-topics'
import { DLQ_OUTPUT, EVENTS_OUTPUT, INGESTION_WARNINGS_OUTPUT, OVERFLOW_OUTPUT } from '../../common/outputs'
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
}
