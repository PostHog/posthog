import Redis from 'ioredis'
import { Consumer, Kafka, KafkaMessage, logLevel, Partitioners, Producer } from 'kafkajs'
import { Pool } from 'pg'
import { v4 as uuidv4 } from 'uuid'

import { defaultConfig } from '../src/config/config'
import { delayUntilEventIngested } from '../tests/helpers/clickhouse'
import { getMetric } from './api'
import { waitForExpect } from './expectations'

let producer: Producer
let postgres: Pool // NOTE: we use a Pool here but it's probably not necessary, but for instance `insertRow` uses a Pool.
let kafka: Kafka
let redis: Redis.Redis

beforeAll(async () => {
    // Setup connections to kafka, clickhouse, and postgres
    postgres = new Pool({
        connectionString: defaultConfig.DATABASE_URL!,
        // We use a pool only for typings sake, but we don't actually need to,
        // so set max connections to 1.
        max: 1,
    })
    kafka = new Kafka({ brokers: [defaultConfig.KAFKA_HOSTS], logLevel: logLevel.NOTHING })
    producer = kafka.producer({ createPartitioner: Partitioners.DefaultPartitioner })
    await producer.connect()
    redis = new Redis(defaultConfig.REDIS_URL)
})

afterAll(async () => {
    await Promise.all([producer.disconnect(), postgres.end(), redis.disconnect()])
})

// Test out some error cases that we wouldn't be able to handle without
// producing to the jobs queue directly.

let dlq: KafkaMessage[]
let dlqConsumer: Consumer

beforeAll(async () => {
    dlq = []
    dlqConsumer = kafka.consumer({ groupId: 'jobs-consumer-test' })
    await dlqConsumer.subscribe({ topic: 'jobs_dlq' })
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

test.concurrent(`handles empty messages`, async () => {
    const key = uuidv4()

    await producer.send({
        topic: 'jobs',
        messages: [
            {
                key: key,
                value: null,
            },
        ],
    })

    const messages = await delayUntilEventIngested(() => dlq.filter((message) => message.key?.toString() === key))
    expect(messages.length).toBe(1)
})

test.concurrent(`handles invalid JSON`, async () => {
    const key = uuidv4()

    await producer.send({
        topic: 'jobs',
        messages: [
            {
                key: key,
                value: 'invalid json',
            },
        ],
    })

    const messages = await delayUntilEventIngested(() => dlq.filter((message) => message.key?.toString() === key))
    expect(messages.length).toBe(1)
})

test.concurrent('consumer updates timestamp exported to prometheus', async () => {
    // NOTE: it may be another event other than the one we emit here that causes
    // the gauge to increase, but pushing this event through should at least
    // ensure that the gauge is updated.
    const metricBefore = await getMetric({
        name: 'latest_processed_timestamp_ms',
        type: 'GAUGE',
        labels: { topic: 'jobs', partition: '0', groupId: 'jobs-inserter' },
    })

    await producer.send({
        topic: 'jobs',
        // NOTE: we don't actually care too much about the contents of the
        // message, just that it triggeres the consumer to try to process it.
        messages: [{ key: '', value: '' }],
    })

    await waitForExpect(async () => {
        const metricAfter = await getMetric({
            name: 'latest_processed_timestamp_ms',
            type: 'GAUGE',
            labels: { topic: 'jobs', partition: '0', groupId: 'jobs-inserter' },
        })
        expect(metricAfter).toBeGreaterThan(metricBefore)
        expect(metricAfter).toBeLessThan(Date.now()) // Make sure, e.g. we're not setting micro seconds
        expect(metricAfter).toBeGreaterThan(Date.now() - 60_000) // Make sure, e.g. we're not setting seconds
    })
})
