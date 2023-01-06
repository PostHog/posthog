import ClickHouse from '@posthog/clickhouse'
import Redis from 'ioredis'
import { Kafka, Partitioners, Producer } from 'kafkajs'
import { Pool } from 'pg'

import { defaultConfig } from '../src/config/config'
import { UUIDT } from '../src/utils/utils'
import { delayUntilEventIngested } from '../tests/helpers/clickhouse'
import { capture, createOrganization, createTeam, fetchEvents, fetchPerformanceEvents } from './api'

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
    `peformance event ingestion: captured, processed, ingested`,
    async () => {
        const teamId = await createTeam(postgres, organizationId)
        const distinctId = new UUIDT().toString()
        const uuid = new UUIDT().toString()

        await capture(producer, teamId, distinctId, uuid, '$performance_event', {
            '0': 'resource',
            $session_id: '$session_id_1',
            $window_id: '$window_id_1',
            $pageview_id: '$pageview_id_1',
            $current_url: '$current_url_1',
        })

        await delayUntilEventIngested(() => fetchPerformanceEvents(clickHouseClient, teamId), 1, 500, 40)
        const events = await fetchEvents(clickHouseClient, teamId)
        expect(events.length).toBe(0)

        const perfEvents = await fetchPerformanceEvents(clickHouseClient, teamId)
        expect(perfEvents.length).toBe(1)

        // processEvent did not modify
        expect(perfEvents[0]).toMatchObject({
            entry_type: 'resource',
            session_id: '$session_id_1',
            window_id: '$window_id_1',
            pageview_id: '$pageview_id_1',
            current_url: '$current_url_1',
        })
    },
    20000
)
