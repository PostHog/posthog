import { AdminClient, CODES, KafkaConsumer, LibrdKafkaError } from 'node-rdkafka'

import { defaultConfig, overrideWithEnv } from '../../src/config/config'
import {
    KAFKA_APP_METRICS,
    KAFKA_APP_METRICS_2,
    KAFKA_BUFFER,
    KAFKA_CDP_CLICKHOUSE_BEHAVIORAL_COHORTS_MATCHES,
    KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS,
    KAFKA_CLICKHOUSE_AI_EVENTS_JSON,
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
    KAFKA_PERFORMANCE_EVENTS,
    KAFKA_PERSON,
    KAFKA_PERSON_DISTINCT_ID,
    KAFKA_PERSON_DISTINCT_ID_OVERRIDES,
    KAFKA_PERSON_UNIQUE_ID,
    KAFKA_PLUGIN_LOG_ENTRIES,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
} from '../../src/config/kafka-topics'
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

export async function resetKafka(extraServerConfig?: Partial<PluginsServerConfig>): Promise<void> {
    const kafkaConfig = buildKafkaConfig(extraServerConfig)
    await createTopics(kafkaConfig, [
        KAFKA_CLICKHOUSE_AI_EVENTS_JSON,
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
        KAFKA_APP_METRICS,
        KAFKA_APP_METRICS_2,
        KAFKA_PERSON,
        KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS,
        KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
        KAFKA_LOG_ENTRIES,
        KAFKA_EVENTS_RECENT_JSON,
        KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES,
        KAFKA_CDP_CLICKHOUSE_BEHAVIORAL_COHORTS_MATCHES,
        KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS,
        KAFKA_COHORT_MEMBERSHIP_CHANGED,
        KAFKA_CLICKHOUSE_TOPHOG,
    ])
}

export async function createTopics(kafkaConfig: any, topics: string[]): Promise<void> {
    const client = AdminClient.create(kafkaConfig)
    await deleteAllTopics(kafkaConfig)
    await createTopicsWithClient(client, topics)
    client.disconnect()
}

/**
 * Create Kafka topics if they don't already exist, without deleting existing topics.
 * Unlike resetKafka, this preserves ClickHouse Kafka engine consumer connections,
 * avoiding the slow reconnection cycle that causes flaky tests.
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

export async function deleteAllTopics(kafkaConfig: any): Promise<void> {
    // Use a consumer to get metadata
    const consumer = new KafkaConsumer(
        {
            ...kafkaConfig,
            'group.id': 'temp-metadata-group',
        },
        {}
    )

    await new Promise<void>((resolve, reject) => {
        consumer.on('ready', () => resolve())
        consumer.on('event.error', (err) => reject(err))
        consumer.connect()
    })

    // Get list of topics first
    const metadata = await new Promise<any>((resolve, reject) => {
        consumer.getMetadata({}, (err: any, metadata: any) => {
            if (err) {
                reject(err)
            } else {
                resolve(metadata)
            }
        })
    })

    consumer.disconnect()

    const topicsToDelete = metadata.topics.map((t: any) => t.name).filter((name: string) => !name.startsWith('__')) // skip internal topics

    if (topicsToDelete.length === 0) {
        console.log('No topics to delete.')
        return
    }

    // Use AdminClient to delete topics
    const adminClient = AdminClient.create(kafkaConfig)
    const timeout = 10000

    // Delete topics one by one
    for (const topic of topicsToDelete) {
        await new Promise<void>((resolve, reject) => {
            adminClient.deleteTopic(topic, timeout, (error: LibrdKafkaError) => {
                if (error) {
                    console.error(`Failed to delete topic ${topic}:`, error)
                    reject(error)
                } else {
                    resolve()
                }
            })
        })
    }

    adminClient.disconnect()
}
