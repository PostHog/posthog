import { AdminClient, CODES, LibrdKafkaError } from 'node-rdkafka'

import { defaultConfig, overrideWithEnv } from '~/common/config/config'
import {
    KAFKA_APP_METRICS_2,
    KAFKA_BUFFER,
    KAFKA_CDP_CLICKHOUSE_BEHAVIORAL_COHORTS_MATCHES,
    KAFKA_CLICKHOUSE_AI_EVENTS_JSON,
    KAFKA_CLICKHOUSE_FLAG_EVALUATIONS,
    KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
    KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS,
    KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
    KAFKA_CLICKHOUSE_TOPHOG,
    KAFKA_COHORT_MEMBERSHIP_CHANGED,
    KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES,
    KAFKA_EVENTS_DEAD_LETTER_QUEUE,
    KAFKA_EVENTS_JSON,
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_ASYNC,
    KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
    KAFKA_EVENTS_RECENT_JSON,
    KAFKA_GROUPS,
    KAFKA_INGESTION_WARNINGS,
    KAFKA_LOG_ENTRIES,
    KAFKA_MESSAGE_ASSETS,
    KAFKA_PERFORMANCE_EVENTS,
    KAFKA_PERSON,
    KAFKA_PERSON_DISTINCT_ID,
    KAFKA_PERSON_DISTINCT_ID_OVERRIDES,
    KAFKA_PERSON_MERGE_EVENTS,
    KAFKA_PERSON_UNIQUE_ID,
    KAFKA_PLUGIN_LOG_ENTRIES,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
} from '~/common/config/kafka-topics'

import { PluginsServerConfig } from '../../src/types'

function buildKafkaConfig(extraServerConfig?: Partial<PluginsServerConfig>) {
    const config = { ...overrideWithEnv(defaultConfig, process.env), ...extraServerConfig }
    return {
        'client.id': 'nodejs-test',
        'metadata.broker.list': (config.KAFKA_HOSTS || '').split(',').join(','),
    }
}

async function createTopicsWithClient(client: ReturnType<typeof AdminClient.create>, topics: string[]): Promise<void> {
    const timeout = 10000
    for (const topic of topics) {
        await new Promise<void>((resolve, reject) => {
            client.createTopic(
                { topic, num_partitions: 1, replication_factor: 1 },
                timeout,
                (error: LibrdKafkaError) => {
                    if (error) {
                        if (error.code === CODES.ERRORS.ERR_TOPIC_ALREADY_EXISTS) {
                            resolve()
                        } else {
                            console.error(`Failed to create topic ${topic}:`, error)
                            reject(error)
                        }
                    } else {
                        resolve()
                    }
                }
            )
        })
    }
}

// Topics that the ClickHouse Kafka engine tables and the ingestion stack expect to
// exist. Created once (idempotently via ensureKafkaTopics) rather than deleted and
// recreated per test, so ClickHouse's Kafka consumers keep their partition assignments.
export const TEST_KAFKA_TOPICS = [
    KAFKA_CLICKHOUSE_AI_EVENTS_JSON,
    KAFKA_CLICKHOUSE_FLAG_EVALUATIONS,
    KAFKA_EVENTS_JSON,
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_BUFFER,
    KAFKA_GROUPS,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
    KAFKA_PERFORMANCE_EVENTS,
    KAFKA_PERSON,
    KAFKA_PERSON_UNIQUE_ID,
    KAFKA_PERSON_DISTINCT_ID,
    KAFKA_PERSON_DISTINCT_ID_OVERRIDES,
    KAFKA_PLUGIN_LOG_ENTRIES,
    KAFKA_EVENTS_DEAD_LETTER_QUEUE,
    KAFKA_EVENTS_PLUGIN_INGESTION_DLQ,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
    KAFKA_EVENTS_PLUGIN_INGESTION_ASYNC,
    KAFKA_INGESTION_WARNINGS,
    KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
    KAFKA_APP_METRICS_2,
    KAFKA_PERSON,
    KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS,
    KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
    KAFKA_LOG_ENTRIES,
    KAFKA_MESSAGE_ASSETS,
    KAFKA_EVENTS_RECENT_JSON,
    KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES,
    KAFKA_CDP_CLICKHOUSE_BEHAVIORAL_COHORTS_MATCHES,
    KAFKA_COHORT_MEMBERSHIP_CHANGED,
    KAFKA_PERSON_MERGE_EVENTS,
    KAFKA_CLICKHOUSE_TOPHOG,
]

// Builds a unique topic name for a test so each test can produce to and consume from an
// isolated input topic without deleting the shared topics ClickHouse subscribes to.
export function createKafkaTestTopicName(baseTopic: string): string {
    return `${baseTopic}_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

/**
 * Create Kafka topics if they don't already exist, without deleting existing topics.
 * The broker is shared across parallel jest workers, so anything that deletes topics
 * wholesale pulls the output topics out from under whatever else is mid-test.
 */
export async function ensureKafkaTopics(
    topics: string[],
    extraServerConfig?: Partial<PluginsServerConfig>
): Promise<void> {
    const kafkaConfig = buildKafkaConfig(extraServerConfig)
    const client = AdminClient.create(kafkaConfig)
    await createTopicsWithClient(client, topics)
    client.disconnect()
}
