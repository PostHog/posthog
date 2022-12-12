import { createServer, Server } from 'http'
import Redis from 'ioredis'
import { Kafka, Partitioners, Producer } from 'kafkajs'
import { Pool } from 'pg'

import { defaultConfig } from '../src/config/config'
import { UUIDT } from '../src/utils/utils'
import { capture, createAndReloadPluginConfig, createOrganization, createPlugin, createTeam, getMetric } from './api'
import { waitForExpect } from './expectations'

let producer: Producer
let postgres: Pool // NOTE: we use a Pool here but it's probably not necessary, but for instance `insertRow` uses a Pool.
let kafka: Kafka
let redis: Redis.Redis
let organizationId: string
let server: Server
const webHookCalledWith: any = {}

beforeAll(async () => {
    // Setup connections to kafka, clickhouse, and postgres
    postgres = new Pool({
        connectionString: defaultConfig.DATABASE_URL!,
        // We use a pool only for typings sake, but we don't actually need to,
        // so set max connections to 1.
        max: 1,
    })
    kafka = new Kafka({ brokers: [defaultConfig.KAFKA_HOSTS] })
    producer = kafka.producer({ createPartitioner: Partitioners.DefaultPartitioner })
    await producer.connect()
    redis = new Redis(defaultConfig.REDIS_URL)

    organizationId = await createOrganization(postgres)

    server = createServer((req, res) => {
        let body = ''
        req.on('data', (chunk) => {
            body += chunk
        })
        req.on('end', () => {
            webHookCalledWith[req.url!] = webHookCalledWith[req.url!] ?? []
            webHookCalledWith[req.url!].push(JSON.parse(body))
            res.writeHead(200, { 'Content-Type': 'text/plain' })
            res.end()
        })
    })
    server.listen()
})

afterAll(async () => {
    await Promise.all([producer.disconnect(), postgres.end(), redis.disconnect()])
    server.close()
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
                await fetch(
                    "http://localhost:${server.address()?.port}/${teamId}", 
                    {method: "POST", body: JSON.stringify(events)}
                )
            }
        `,
    })
    const pluginConfig = await createAndReloadPluginConfig(postgres, teamId, plugin.id, redis)

    // First let's capture an event and wait for it to be ingested so
    // so we can check that the historical event is the same as the one
    // passed to processEvent on initial ingestion.
    const sentAt = new Date(Date.now())
    await capture(
        producer,
        teamId,
        distinctId,
        uuid,
        '$autocapture',
        {
            name: 'hehe',
            uuid: new UUIDT().toString(),
            $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' }],
        },
        null,
        sentAt
    )

    // Then check that the exportEvents function was called
    const [exportedEvent] = await waitForExpect(() => {
        const exportEvents = webHookCalledWith[`/${teamId}`]
        expect(exportEvents.length).toBeGreaterThan(0)
        return exportEvents[0]
    }, 20_000)

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
                        dateRange: [
                            new Date(sentAt.getTime() - 10000).toISOString(),
                            new Date(Date.now()).toISOString(),
                        ],
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
    await waitForExpect(
        () => {
            const historicallyExportedEvents = webHookCalledWith[`/${teamId}`].filter((events) =>
                events.some((event) => event.properties['$$is_historical_export_event'])
            )
            expect(historicallyExportedEvents.length).toBeGreaterThan(0)

            expect.objectContaining({
                ...exportedEvent,
                ip: '', // NOTE: for some reason this is "" when exported historically, but null otherwise.
                // NOTE: it's important that event, sent_at, uuid, and distinct_id
                // are preserved and are stable for ClickHouse deduplication to
                // function as expected.
                event: '$autocapture',
                sent_at: sentAt.toISOString(),
                uuid: uuid,
                distinct_id: distinctId,
                properties: {
                    ...exportedEvent.properties,
                    $$is_historical_export_event: true,
                    $$historical_export_timestamp: expect.any(String),
                    $$historical_export_source_db: 'clickhouse',
                },
            })
        },
        20_000,
        1_000
    )
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
    }, 10_000)
})
