import { Consumer, Kafka, KafkaMessage, logLevel, Partitioners, Producer } from 'kafkajs'
import { v4 as uuidv4 } from 'uuid'

import { defaultConfig } from '../src/config/config'
import { delayUntilEventIngested } from '../tests/helpers/clickhouse'

let producer: Producer
let kafka: Kafka

beforeAll(async () => {
    kafka = new Kafka({ brokers: [defaultConfig.KAFKA_HOSTS], logLevel: logLevel.NOTHING })
    producer = kafka.producer({ createPartitioner: Partitioners.DefaultPartitioner })
    await producer.connect()
})

afterAll(async () => {
    await Promise.all([producer.disconnect()])
})

// Test out some error cases that we wouldn't be able to handle without
// producing to the jobs queue directly.

let dlq: KafkaMessage[]
let dlqConsumer: Consumer

const topics = [
    // NOTE: for introducing the ClickHouse inserter consumer, we are initially
    // only enabling for App Metrics and Ingestion Warnings. We will enable for
    // the rest assuming performance is good enough.
    'clickhouse_app_metrics',

    // TODO: enable these other topics assuming the above topics work well.
    // 'clickhouse_ingestion_warnings',
    // 'clickhouse_events_json',
    // 'clickhouse_groups',
    // 'clickhouse_person',
    // 'clickhouse_person_distinct_id',
    // 'plugin_log_entries',
    // 'clickhouse_session_recording_events',

    // NOTE: we do not check events_dead_letter_queue here, as this doesn't push
    // into a dead letter itself
    // 'events_dead_letter_queue',
] as const

beforeAll(async () => {
    dlq = []
    dlqConsumer = kafka.consumer({ groupId: 'clickhouse-inserter-test' })
    await dlqConsumer.subscribe({
        topics: topics.map((topic) => `${topic}_inserter_dlq`),
    })
    await dlqConsumer.run({
        eachMessage: ({ message }) => {
            dlq.push(message)
            return Promise.resolve()
        },
    })
})

afterAll(async () => {
    await dlqConsumer.disconnect()
})

describe.each(topics.map((topic) => [{ topic }]))('clickhouse-inserter', ({ topic }) => {
    describe(topic, () => {
        test.concurrent(`handles empty messages`, async () => {
            const key = uuidv4()

            await producer.send({
                topic: topic,
                messages: [
                    {
                        key: key,
                        value: null,
                    },
                ],
            })

            const messages = await delayUntilEventIngested(() =>
                dlq.filter((message) => message.key?.toString() === key)
            )
            expect(messages.length).toBe(1)
        })

        test.concurrent(`handles invalid JSON`, async () => {
            const key = uuidv4()

            await producer.send({
                topic: topic,
                messages: [
                    {
                        key: key,
                        value: 'invalid json',
                    },
                ],
            })

            const messages = await delayUntilEventIngested(() =>
                dlq.filter((message) => message.key?.toString() === key)
            )
            expect(messages.length).toBe(1)
        })

        test.concurrent(`handles invalid schema`, async () => {
            const key = uuidv4()

            await producer.send({
                topic: topic,
                messages: [
                    {
                        key: key,
                        value: JSON.stringify({ invalid: 'schema' }),
                    },
                ],
            })

            const messages = await delayUntilEventIngested(() =>
                dlq.filter((message) => message.key?.toString() === key)
            )
            expect(messages.length).toBe(1)
        })
    })
})
