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
    fetchEvents,
    fetchPluginLogEntries,
} from './api'

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

test.concurrent(`exports: exporting events on ingestion`, async () => {
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
    const teamId = await createTeam(postgres, organizationId)
    const pluginConfig = await createAndReloadPluginConfig(postgres, teamId, plugin.id, redis)
    const distinctId = new UUIDT().toString()
    const uuid = new UUIDT().toString()

    // First let's ingest an event
    await capture(producer, teamId, distinctId, uuid, 'custom event', {
        name: 'hehe',
        uuid: new UUIDT().toString(),
    })

    const events = await delayUntilEventIngested(() => fetchEvents(clickHouseClient, teamId), 1, 500, 40)
    expect(events.length).toBe(1)

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

    const exportedEvents = exportEvents[0].message[1]
    expect(exportedEvents).toEqual([
        expect.objectContaining({
            distinct_id: distinctId,
            team_id: teamId,
            event: 'custom event',
            properties: expect.objectContaining({
                name: 'hehe',
                uuid: uuid,
            }),
            timestamp: expect.any(String),
            uuid: uuid,
            elements: [],
        }),
    ])
})

test.concurrent(`exports: exporting $autocapture events on ingestion`, async () => {
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
    const teamId = await createTeam(postgres, organizationId)
    const pluginConfig = await createAndReloadPluginConfig(postgres, teamId, plugin.id, redis)
    const distinctId = new UUIDT().toString()
    const uuid = new UUIDT().toString()

    // First let's ingest an event
    await capture(producer, teamId, distinctId, uuid, '$autocapture', {
        name: 'hehe',
        uuid: new UUIDT().toString(),
        $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' }],
    })

    const events = await delayUntilEventIngested(() => fetchEvents(clickHouseClient, teamId), 1, 500, 40)
    expect(events.length).toBe(1)

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

    const exportedEvents = exportEvents[0].message[1]
    expect(exportedEvents).toEqual([
        expect.objectContaining({
            distinct_id: distinctId,
            team_id: teamId,
            event: '$autocapture',
            properties: expect.objectContaining({
                name: 'hehe',
                uuid: uuid,
            }),
            timestamp: expect.any(String),
            uuid: uuid,
            elements: [
                {
                    tag_name: 'div',
                    nth_child: 1,
                    nth_of_type: 2,
                    order: 0,
                    $el_text: '💻',
                    text: '💻',
                    attributes: {},
                },
            ],
        }),
    ])
})

test.concurrent(`exports: historical exports`, async () => {
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
                    type: 'Export historical events',
                    pluginConfigId: pluginConfig.id,
                    pluginConfigTeam: teamId,
                    payload: {
                        dateFrom: new Date(Date.now() - 60000).toISOString(),
                        dateTo: new Date(Date.now()).toISOString(),
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
