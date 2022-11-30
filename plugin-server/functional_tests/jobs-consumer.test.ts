import Redis from 'ioredis'
import { Consumer, Kafka, KafkaMessage, logLevel,Partitioners, Producer } from 'kafkajs'
import { Pool } from 'pg'
import { v4 as uuidv4 } from 'uuid'

import { defaultConfig } from '../src/config/config'
import { delayUntilEventIngested } from '../tests/helpers/clickhouse'

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

test.concurrent(`jobs-consumer: handles empty messages`, async () => {
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

test.concurrent(`jobs-consumer: handles invalid JSON`, async () => {
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
