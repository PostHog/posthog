import ClickHouse from '@posthog/clickhouse'
import Redis from 'ioredis'
import { CompressionCodecs, CompressionTypes, Consumer, Kafka, KafkaMessage, Partitioners, Producer } from 'kafkajs'
// @ts-expect-error no type definitions
import SnappyCodec from 'kafkajs-snappy'
import { Pool } from 'pg'
import { v4 as uuidv4 } from 'uuid'

import { defaultConfig } from '../src/config/config'
import { UUIDT } from '../src/utils/utils'
import { capture, createOrganization, createTeam, fetchSessionRecordingsEvents } from './api'
import { waitForExpect } from './expectations'

CompressionCodecs[CompressionTypes.Snappy] = SnappyCodec

let producer: Producer
let clickHouseClient: ClickHouse
let postgres: Pool // NOTE: we use a Pool here but it's probably not necessary, but for instance `insertRow` uses a Pool.
let kafka: Kafka
let redis: Redis.Redis
let organizationId: string

let dlq: KafkaMessage[]
let dlqConsumer: Consumer

beforeAll(async () => {
    // Setup connections to kafka, clickhouse, and postgres
    postgres = new Pool({
        connectionString: defaultConfig.DATABASE_URL!,
        // We use a pool only for typings sake, but we don't actually need to,
        // so set max connections to 1.
        max: 1,
    })
    clickHouseClient = new ClickHouse({
        host: defaultConfig.CLICKHOUSE_HOST,
        port: 8123,
        dataObjects: true,
        queryOptions: {
            database: defaultConfig.CLICKHOUSE_DATABASE,
            output_format_json_quote_64bit_integers: false,
        },
    })
    kafka = new Kafka({ brokers: [defaultConfig.KAFKA_HOSTS] })
    producer = kafka.producer({ createPartitioner: Partitioners.DefaultPartitioner })
    await producer.connect()
    redis = new Redis(defaultConfig.REDIS_URL)

    dlq = []
    dlqConsumer = kafka.consumer({ groupId: 'session_recording_events_test' })
    await dlqConsumer.subscribe({ topic: 'session_recording_events_dlq' })
    await dlqConsumer.run({
        eachMessage: ({ message }) => {
            dlq.push(message)
            return Promise.resolve()
        },
    })

    organizationId = await createOrganization(postgres)
})

afterAll(async () => {
    await Promise.all([producer.disconnect(), postgres.end(), redis.disconnect(), await dlqConsumer.disconnect()])
})

test.concurrent(
    `snapshot captured, processed, ingested via events_plugin_ingestion topic`,
    async () => {
        // We have switched from pushing the `events_plugin_ingestion` to
        // pushing to `session_recording_events`. There will still be session
        // recording events in the `events_plugin_ingestion` topic for a while
        // so we need to still handle these events with the current consumer.
        const teamId = await createTeam(postgres, organizationId)
        const distinctId = new UUIDT().toString()
        const uuid = new UUIDT().toString()

        await capture(producer, teamId, distinctId, uuid, '$snapshot', {
            $session_id: '1234abc',
            $snapshot_data: 'yes way',
        })

        await waitForExpect(async () => {
            const events = await fetchSessionRecordingsEvents(clickHouseClient, teamId)
            expect(events.length).toBe(1)

            // processEvent did not modify
            expect(events[0].snapshot_data).toEqual('yes way')
        })
    },
    20000
)

test.concurrent(
    `snapshot captured, processed, ingested via session_recording_events topic`,
    async () => {
        const teamId = await createTeam(postgres, organizationId)
        const distinctId = new UUIDT().toString()
        const uuid = new UUIDT().toString()

        await capture(
            producer,
            teamId,
            distinctId,
            uuid,
            '$snapshot',
            {
                $session_id: '1234abc',
                $snapshot_data: 'yes way',
            },
            null,
            new Date(),
            new Date(),
            new Date(),
            'session_recording_events'
        )

        await waitForExpect(async () => {
            const events = await fetchSessionRecordingsEvents(clickHouseClient, teamId)
            expect(events.length).toBe(1)

            // processEvent did not modify
            expect(events[0].snapshot_data).toEqual('yes way')
        })
    },
    20000
)

test.concurrent(
    `consumer handles empty messages`,
    async () => {
        const key = uuidv4()

        await producer.send({
            topic: 'session_recording_events',
            messages: [
                {
                    key: key,
                    value: null,
                },
            ],
        })

        await waitForExpect(() => {
            const messages = dlq.filter((message) => message.key?.toString() === key)
            expect(messages.length).toBe(1)
        })
    },
    20000
)

test.concurrent(`handles invalid JSON`, async () => {
    const key = uuidv4()

    await producer.send({
        topic: 'session_recording_events',
        messages: [
            {
                key: key,
                value: 'invalid json',
            },
        ],
    })

    await waitForExpect(() => {
        const messages = dlq.filter((message) => message.key?.toString() === key)
        expect(messages.length).toBe(1)
    })
})

test.concurrent(`handles message with no token`, async () => {
    const key = uuidv4()

    await producer.send({
        topic: 'session_recording_events',
        messages: [
            {
                key: key,
                value: JSON.stringify({}),
            },
        ],
    })

    await waitForExpect(() => {
        const messages = dlq.filter((message) => message.key?.toString() === key)
        expect(messages.length).toBe(1)
    })
})

test.concurrent(`handles message with token and no associated team_id`, async () => {
    const key = uuidv4()
    const token = uuidv4()

    await producer.send({
        topic: 'session_recording_events',
        messages: [
            {
                key: key,
                value: JSON.stringify({
                    token: token,
                }),
            },
        ],
    })

    await waitForExpect(() => {
        const messages = dlq.filter((message) => message.key?.toString() === key)
        expect(messages.length).toBe(1)
    })
})

// TODO: implement schema validation and add a test.
