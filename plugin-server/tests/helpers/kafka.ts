import { Kafka, logLevel } from 'kafkajs'

import { defaultConfig, overrideWithEnv } from '../../src/config/config'
import {
    KAFKA_EVENTS,
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_GROUPS,
    KAFKA_PERSON,
    KAFKA_PERSON_UNIQUE_ID,
    KAFKA_PLUGIN_LOG_ENTRIES,
    KAFKA_SESSION_RECORDING_EVENTS,
} from '../../src/config/kafka-topics'
import { PluginsServerConfig } from '../../src/types'
import { delay, UUIDT } from '../../src/utils/utils'
import { KAFKA_EVENTS_DEAD_LETTER_QUEUE } from './../../src/config/kafka-topics'

/** Clear the kafka queue */
export async function resetKafka(extraServerConfig: Partial<PluginsServerConfig>, delayMs = 2000): Promise<true> {
    console.log('Resetting Kafka!')
    const config = { ...overrideWithEnv(defaultConfig, process.env), ...extraServerConfig }
    const kafka = new Kafka({
        clientId: `plugin-server-test-${new UUIDT()}`,
        brokers: (config.KAFKA_HOSTS || '').split(','),
        logLevel: logLevel.WARN,
    })
    const producer = kafka.producer()
    const consumer = kafka.consumer({
        groupId: 'clickhouse-ingestion-test',
    })
    const messages = []

    await createTopics(kafka, [
        KAFKA_EVENTS,
        KAFKA_EVENTS_PLUGIN_INGESTION,
        KAFKA_GROUPS,
        KAFKA_SESSION_RECORDING_EVENTS,
        KAFKA_PERSON,
        KAFKA_PERSON_UNIQUE_ID,
        KAFKA_PLUGIN_LOG_ENTRIES,
        KAFKA_EVENTS_DEAD_LETTER_QUEUE,
    ])

    await new Promise<void>(async (resolve, reject) => {
        console.info('setting group join and crash listeners')
        const { CONNECT, GROUP_JOIN, CRASH } = consumer.events
        consumer.on(CONNECT, () => {
            console.log('consumer connected to kafka')
        })
        consumer.on(GROUP_JOIN, () => {
            console.log('joined group')
            resolve()
        })
        consumer.on(CRASH, ({ payload: { error } }) => reject(error))

        console.info('connecting producer')
        await producer.connect()

        console.info('subscribing consumer')
        await consumer.subscribe({ topic: KAFKA_EVENTS_PLUGIN_INGESTION })

        console.info('running consumer')
        await consumer.run({
            eachMessage: async (payload) => {
                await Promise.resolve()
                console.info('message received!')
                messages.push(payload)
            },
        })

        console.info(`awaiting ${delayMs} ms before disconnecting`)
        await delay(delayMs)

        console.info('disconnecting producer')
        await producer.disconnect()

        console.info('stopping consumer')
        await consumer.stop()

        console.info('disconnecting consumer')
        await consumer.disconnect()
    })

    return true
}

async function createTopics(kafka: Kafka, topics: string[]) {
    const admin = kafka.admin()
    await admin.connect()
    await admin.createTopics({
        waitForLeaders: true,
        topics: topics.map((topic) => ({ topic })),
    })
    await admin.disconnect()
}
