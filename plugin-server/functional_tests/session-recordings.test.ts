import ClickHouse from '@posthog/clickhouse'
import Redis from 'ioredis'
import { Kafka, Partitioners, Producer } from 'kafkajs'
import { Pool } from 'pg'

import { defaultConfig } from '../src/config/config'
import { UUIDT } from '../src/utils/utils'
import { capture, createOrganization, createTeam, fetchSessionRecordingsEvents } from './api'
import { waitForExpect } from './expectations'

let producer: Producer
let clickHouseClient: ClickHouse
let postgres: Pool // NOTE: we use a Pool here but it's probably not necessary, but for instance `insertRow` uses a Pool.
let kafka: Kafka
let redis: Redis.Redis
let organizationId: string

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

    organizationId = await createOrganization(postgres)
})

afterAll(async () => {
    await Promise.all([producer.disconnect(), postgres.end(), redis.disconnect()])
})

test.concurrent(
    `session recording ingestion: snapshot captured, processed, ingested`,
    async () => {
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
