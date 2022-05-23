import { Kafka, logLevel } from 'kafkajs'

import { defaultConfig, overrideWithEnv } from '../../src/config/config'
import {
    KAFKA_EVENTS,
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_GROUPS,
    KAFKA_PERSON,
    KAFKA_PERSON_DISTINCT_ID,
    KAFKA_PERSON_UNIQUE_ID,
    KAFKA_PLUGIN_LOG_ENTRIES,
    KAFKA_SESSION_RECORDING_EVENTS,
} from '../../src/config/kafka-topics'
import { PluginsServerConfig } from '../../src/types'
import { UUIDT } from '../../src/utils/utils'
import { KAFKA_EVENTS_DEAD_LETTER_QUEUE } from './../../src/config/kafka-topics'

/** Clear the kafka queue */
export async function resetKafka(extraServerConfig?: Partial<PluginsServerConfig>): Promise<void> {
    const config = { ...overrideWithEnv(defaultConfig, process.env), ...extraServerConfig }
    const kafka = new Kafka({
        clientId: `plugin-server-test-${new UUIDT()}`,
        brokers: (config.KAFKA_HOSTS || '').split(','),
        logLevel: logLevel.WARN,
    })

    await createTopics(kafka, [
        KAFKA_EVENTS,
        KAFKA_EVENTS_PLUGIN_INGESTION,
        KAFKA_GROUPS,
        KAFKA_SESSION_RECORDING_EVENTS,
        KAFKA_PERSON,
        KAFKA_PERSON_UNIQUE_ID,
        KAFKA_PERSON_DISTINCT_ID,
        KAFKA_PLUGIN_LOG_ENTRIES,
        KAFKA_EVENTS_DEAD_LETTER_QUEUE,
    ])
}

async function createTopics(kafka: Kafka, topics: string[]) {
    const admin = kafka.admin()
    await admin.connect()

    const existingTopics = await admin.listTopics()
    const topicsToCreate = topics.filter((topic) => !existingTopics.includes(topic)).map((topic) => ({ topic }))

    if (topicsToCreate.length > 0) {
        await admin.createTopics({
            waitForLeaders: true,
            topics: topicsToCreate,
        })
    }
    await admin.disconnect()
}
