import ClickHouse from '@posthog/clickhouse'
import Redis from 'ioredis'
import { Kafka, Partitioners, Producer } from 'kafkajs'
import { Pool } from 'pg'

import { defaultConfig } from '../src/config/config'
import { UUIDT } from '../src/utils/utils'
import { delayUntilEventIngested } from '../tests/helpers/clickhouse'
import {
    capture,
    createAndReloadPluginConfig,
    createOrganization,
    createPlugin,
    createTeam,
    fetchPluginLogEntries,
    getMetric,
} from './api'
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

test.concurrent(`exports: historical exports v2`, async () => {
    const teamId = await createTeam(postgres, organizationId)
    const distinctId = new UUIDT().toString()
    const uuid = new UUIDT().toString()

    const plugin = await createPlugin(postgres, {
        organization_id: organizationId,
        name: 'export plugin',
        plugin_type: 'source',
        is_global: false,
        source__index_ts: `
            export const exportEvents = async (events, { global, config }) => {
                console.info(JSON.stringify(['exportEvents', events]))
            }
        `,
    })
    const pluginConfig = await createAndReloadPluginConfig(postgres, teamId, plugin.id, redis)

    // First let's capture an event and wait for it to be ingested so
    // so we can check that the historical event is the same as the one
    // passed to processEvent on initial ingestion.
    await capture(producer, teamId, distinctId, uuid, '$autocapture', {
        name: 'hehe',
        uuid: new UUIDT().toString(),
        $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' }],
    })

    // Then check that the exportEvents function was called
    const exportEvents = await delayUntilEventIngested(
        async () =>
            (
                await fetchPluginLogEntries(clickHouseClient, pluginConfig.id)
            ).filter(({ message: [method] }) => method === 'exportEvents'),
        1,
        500,
        40
    )

    expect(exportEvents.length).toBeGreaterThan(0)
    const [exportedEvent] = exportEvents[0].message[1]

    // NOTE: the frontend doesn't actually push to this queue but rather
    // adds directly to PostgreSQL using the graphile-worker stored
    // procedure `add_job`. I'd rather keep these tests graphile
    // unaware.
    await producer.send({
        topic: 'jobs',
        messages: [
            {
                key: teamId.toString(),
                value: JSON.stringify({
                    type: 'Export historical events V2',
                    pluginConfigId: pluginConfig.id,
                    pluginConfigTeam: teamId,
                    payload: {
                        dateRange: [new Date(Date.now() - 60000).toISOString(), new Date(Date.now()).toISOString()],
                        $job_id: 'test',
                        parallelism: 1,
                    },
                }),
            },
        ],
    })

    // Then check that the exportEvents function was called with the
    // same data that was used with the non-historical export, with the
    // additions of details related to the historical export.
    const historicallyExportedEvents = await delayUntilEventIngested(
        async () =>
            (await fetchPluginLogEntries(clickHouseClient, pluginConfig.id))
                .filter(({ message: [method] }) => method === 'exportEvents')
                .filter(({ message: [, events] }) =>
                    events.some((event) => event.properties['$$is_historical_export_event'])
                ),
        1,
        500,
        40
    )

    expect(historicallyExportedEvents.length).toBeGreaterThan(0)

    const historicallyExportedEvent = historicallyExportedEvents[0].message[1]
    expect(historicallyExportedEvent).toEqual([
        expect.objectContaining({
            ...exportedEvent,
            ip: '', // NOTE: for some reason this is "" when exported historically, but null otherwise.
            properties: {
                ...exportedEvent.properties,
                $$is_historical_export_event: true,
                $$historical_export_timestamp: expect.any(String),
                $$historical_export_source_db: 'clickhouse',
            },
        }),
    ])
})

test.concurrent('consumer updates timestamp exported to prometheus', async () => {
    // NOTE: it may be another event other than the one we emit here that causes
    // the gauge to increase, but pushing this event through should at least
    // ensure that the gauge is updated.
    const teamId = await createTeam(postgres, organizationId)
    const distinctId = new UUIDT().toString()
    const uuid = new UUIDT().toString()

    const metricBefore = await getMetric({
        name: 'latest_processed_timestamp_ms',
        type: 'GAUGE',
        labels: { topic: 'clickhouse_events_json', partition: '0', groupId: 'async_handlers' },
    })

    await capture(producer, teamId, distinctId, uuid, '$autocapture', {
        name: 'hehe',
        uuid: new UUIDT().toString(),
        $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' }],
    })

    await waitForExpect(async () => {
        const metricAfter = await getMetric({
            name: 'latest_processed_timestamp_ms',
            type: 'GAUGE',
            labels: { topic: 'clickhouse_events_json', partition: '0', groupId: 'async_handlers' },
        })
        expect(metricAfter).toBeGreaterThan(metricBefore)
        expect(metricAfter).toBeLessThan(Date.now()) // Make sure, e.g. we're not setting micro seconds
        expect(metricAfter).toBeGreaterThan(Date.now() - 60_000) // Make sure, e.g. we're not setting seconds
    })
})
