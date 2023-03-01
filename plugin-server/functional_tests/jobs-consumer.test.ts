import Redis from 'ioredis'
import { Consumer, Kafka, KafkaMessage, logLevel } from 'kafkajs'
import { Pool } from 'pg'
import { v4 as uuidv4 } from 'uuid'

import { defaultConfig } from '../src/config/config'
import { getMetric } from './api'
import { waitForExpect } from './expectations'
import { produce } from './kafka'

let postgres: Pool // NOTE: we use a Pool here but it's probably not necessary, but for instance `insertRow` uses a Pool.
let kafka: Kafka
let redis: Redis.Redis

beforeAll(() => {
    // Setup connections to kafka, clickhouse, and postgres
    postgres = new Pool({
        connectionString: defaultConfig.DATABASE_URL!,
        // We use a pool only for typings sake, but we don't actually need to,
        // so set max connections to 1.
        max: 1,
    })
    kafka = new Kafka({ brokers: [defaultConfig.KAFKA_HOSTS], logLevel: logLevel.NOTHING })
    redis = new Redis(defaultConfig.REDIS_URL)
})

afterAll(async () => {
    await Promise.all([postgres.end(), redis.disconnect()])
})

describe('dlq handling', () => {
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

        await produce({ topic: 'jobs', message: null, key })

        await waitForExpect(() => {
            const messages = dlq.filter((message) => message.key?.toString() === key)
            expect(messages.length).toBe(1)
        })
    })

    test.concurrent(`handles invalid JSON`, async () => {
        const key = uuidv4()

        await produce({ topic: 'jobs', message: Buffer.from('invalid json'), key })

        await waitForExpect(() => {
            const messages = dlq.filter((message) => message.key?.toString() === key)
            expect(messages.length).toBe(1)
        })
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

        await produce({ topic: 'jobs', message: Buffer.from(''), key: '' })

        await waitForExpect(async () => {
            const metricAfter = await getMetric({
                name: 'latest_processed_timestamp_ms',
                type: 'GAUGE',
                labels: { topic: 'jobs', partition: '0', groupId: 'jobs-inserter' },
            })
            expect(metricAfter).toBeGreaterThan(metricBefore)
            expect(metricAfter).toBeLessThan(Date.now()) // Make sure, e.g. we're not setting micro seconds
            expect(metricAfter).toBeGreaterThan(Date.now() - 60_000) // Make sure, e.g. we're not setting seconds
        }, 10_000)
    })
})
