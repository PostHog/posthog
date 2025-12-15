import { AdminClient, CODES, KafkaConsumer, LibrdKafkaError } from 'node-rdkafka'

import { defaultConfig, overrideWithEnv } from '../../src/config/config'
import {
    KAFKA_APP_METRICS,
    KAFKA_APP_METRICS_2,
    KAFKA_BUFFER,
    KAFKA_CDP_CLICKHOUSE_BEHAVIORAL_COHORTS_MATCHES,
    KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS,
    KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
    KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS,
    KAFKA_COHORT_MEMBERSHIP_CHANGED,
    KAFKA_COHORT_MEMBERSHIP_CHANGED_TRIGGER,
    KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES,
    KAFKA_EVENTS_DEAD_LETTER_QUEUE,
    KAFKA_EVENTS_JSON,
    KAFKA_EVENTS_PLUGIN_INGESTION,
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

export async function resetKafka(extraServerConfig?: Partial<PluginsServerConfig>): Promise<void> {
    const config = { ...overrideWithEnv(defaultConfig, process.env), ...extraServerConfig }

    const kafkaConfig = {
        'client.id': 'plugin-server-test',
        'metadata.broker.list': (config.KAFKA_HOSTS || '').split(',').join(','),
    }

    await createTopics(kafkaConfig, [
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
        KAFKA_INGESTION_WARNINGS,
        KAFKA_CLICKHOUSE_HEATMAP_EVENTS,
        KAFKA_APP_METRICS,
        KAFKA_APP_METRICS_2,
        KAFKA_PERSON,
        KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS,
        KAFKA_LOG_ENTRIES,
        KAFKA_EVENTS_RECENT_JSON,
        KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES,
        KAFKA_CDP_CLICKHOUSE_BEHAVIORAL_COHORTS_MATCHES,
        KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS,
        KAFKA_COHORT_MEMBERSHIP_CHANGED,
        KAFKA_COHORT_MEMBERSHIP_CHANGED_TRIGGER,
    ])
}

export async function createTopics(kafkaConfig: any, topics: string[]): Promise<void> {
    const client = AdminClient.create(kafkaConfig)
    const timeout = 10000

    await deleteAllTopics(kafkaConfig)

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
