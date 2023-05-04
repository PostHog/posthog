import { uuid4 } from '@sentry/utils'
import { createServer, Server } from 'http'

import { UUIDT } from '../src/utils/utils'
import { capture, createAndReloadPluginConfig, createOrganization, createPlugin, createTeam, getMetric } from './api'
import { waitForExpect } from './expectations'
import { produce } from './kafka'

// Exports are coordinated by a scheduled task that runs every minute, so we
// increase the wait time to give us a bit of leeway.
jest.setTimeout(120_000)

let organizationId: string
let server: Server
const webHookCalledWith: any = {}

beforeAll(async () => {
    organizationId = await createOrganization()

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

    await new Promise((resolve) => {
        server.on('listening', resolve)
        server.listen()
    })
})

afterAll(() => {
    server.close()
})

test.concurrent(`exports: historical exports v2`, async () => {
    // This test runs through checking:
    //
    //  1. the payload we send for "live" events i.e. events we are exporting as
    //     they are ingested
    //  2. running an historical export, and checking the payload is
    //     sufficiently the same as the live event export
    //  3. running an historical export again, and checking the payload is the
    //     same as the previous historical export
    //
    // It's important the the timestamp and sent_at are the same, as otherwise
    // the event time committed to the database will be different, and will
    // result in duplicates.
    //
    // The way the merging in ClickHouse works means that we will not be able to
    // guarantee events with the same sorting key will be dedpulicated, but we
    // should do a best effort at ensuring they are the same.

    const teamId = await createTeam(organizationId)
    const distinctId = new UUIDT().toString()
    const uuid = new UUIDT().toString()
    const testUuid = new UUIDT().toString()

    const plugin = await createPlugin({
        organization_id: organizationId,
        name: 'export plugin',
        plugin_type: 'source',
        is_global: false,
        source__index_ts: `
            export const exportEvents = async (events, { global, config }) => {
                await fetch(
                    "http://localhost:${server.address()?.port}/${testUuid}", 
                    {method: "POST", body: JSON.stringify(events)}
                )
            }
        `,
    })
    const pluginConfig = await createAndReloadPluginConfig(teamId, plugin.id)

    // First let's capture an event and wait for it to be ingested so
    // so we can check that the historical event is the same as the one
    // passed to processEvent on initial ingestion.
    const eventTime = new Date('2022-01-01T05:08:00.000Z')
    const sentAt = new Date('2022-01-01T05:10:00.000Z')
    const now = new Date('2022-01-01T05:00:00.000Z')
    const skewAdjustedTimestamp = new Date('2022-01-01T04:58:00.000Z')
    const properties = {
        name: 'hehe',
        uuid: new UUIDT().toString(),
        $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' }],
    }
    await capture({ teamId, distinctId, uuid, event: '$autocapture', properties, token: null, sentAt, eventTime, now })

    // Then check that the exportEvents function was called
    const [exportedEvent] = await waitForExpect(() => {
        const [exportEvents] = webHookCalledWith[`/${testUuid}`]
        expect(exportEvents.length).toBe(1)
        return exportEvents
    }, 20_000)

    expect(exportedEvent).toEqual(
        expect.objectContaining({
            event: '$autocapture',
            // NOTE: this timestamp takes into account the time skew between
            // `now` and `sent_at`.
            timestamp: skewAdjustedTimestamp.toISOString(),
            uuid: uuid,
            distinct_id: distinctId,
            properties: expect.objectContaining({
                name: properties.name,
                // TODO: do not override uuid property with event id
                uuid: uuid, // NOTE: uuid added to properties is overridden by the event uuid
            }),
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
            team_id: teamId,
        })
    )

    await createHistoricalExportJob({
        teamId,
        pluginConfigId: pluginConfig.id,
        dateRange: [
            new Date(skewAdjustedTimestamp.getTime() - 10000).toISOString(),
            new Date(skewAdjustedTimestamp.getTime() + 10000).toISOString(),
        ],
    })

    // Then check that the exportEvents function was called with the
    // same data that was used with the non-historical export, with the
    // additions of details related to the historical export.
    const firstExportedEvent = await waitForExpect(
        () => {
            const [historicallyExportedEvents] = webHookCalledWith[`/${testUuid}`].filter((events) => {
                return events.some((event) => event.properties['$$is_historical_export_event'])
            })

            expect(historicallyExportedEvents.length).toBe(1)

            return historicallyExportedEvents[0]
        },
        // NOTE: exports are driven by a scheduled task that runs every minute,
        // so we need to wait a while.
        90_000,
        1_000
    )

    expect(firstExportedEvent).toEqual({
        ...exportedEvent,
        ip: '', // NOTE: for some reason this is "" when exported historically, but null otherwise.
        // NOTE: it's important that event, sent_at, uuid, and distinct_id
        // are preserved and are stable for ClickHouse deduplication to
        // function as expected.
        site_url: '',
        // NOTE: we get a now attribute which is set to the time the
        // event was converted from the ClickHouse event. We do not
        // use the `now` attribute in the /capture endpoint, so this
        // should be ok to leave.
        now: expect.any(String),
        properties: {
            ...exportedEvent.properties,
            $$is_historical_export_event: true,
            $$historical_export_timestamp: expect.any(String),
            $$historical_export_source_db: 'clickhouse',
        },
    })

    // Run the export again to ensure we get the same results, such that we can
    // re-run exports without creating duplicates. We use a different plugin
    // config as otherwise it seems the second export doesn't start.
    const secondTestUuid = uuid4()
    const secondPlugin = await createPlugin({
        organization_id: organizationId,
        name: 'export plugin',
        plugin_type: 'source',
        is_global: false,
        source__index_ts: `
            export const exportEvents = async (events, { global, config }) => {
                await fetch(
                    "http://localhost:${server.address()?.port}/${secondTestUuid}", 
                    {method: "POST", body: JSON.stringify(events)}
                )
            }
        `,
    })
    const secondPluginConfig = await createAndReloadPluginConfig(teamId, secondPlugin.id)

    await createHistoricalExportJob({
        teamId,
        pluginConfigId: secondPluginConfig.id,
        dateRange: [
            new Date(skewAdjustedTimestamp.getTime() - 10000).toISOString(),
            new Date(skewAdjustedTimestamp.getTime() + 10000).toISOString(),
        ],
    })

    const historicallyExportedEvents = await waitForExpect(
        () => {
            const [historicallyExportedEvents] = webHookCalledWith[`/${secondTestUuid}`]
            expect(historicallyExportedEvents.length).toBe(1)
            return historicallyExportedEvents
        },
        // NOTE: exports are driven by a scheduled task that runs every minute,
        // so we need to wait a while.
        90_000,
        1_000
    )

    expect(historicallyExportedEvents).toEqual([
        {
            ...firstExportedEvent,
            // NOTE: we get a now attribute which is set to the time the
            // event was converted from the ClickHouse event. We do not
            // use the `now` attribute in the /capture endpoint, so this
            // should be ok to leave.
            now: expect.any(String),
            properties: { ...firstExportedEvent.properties, $$historical_export_timestamp: expect.any(String) },
        },
    ])
})

test.concurrent('consumer updates timestamp exported to prometheus', async () => {
    // NOTE: it may be another event other than the one we emit here that causes
    // the gauge to increase, but pushing this event through should at least
    // ensure that the gauge is updated.
    const teamId = await createTeam(organizationId)
    const distinctId = new UUIDT().toString()
    const uuid = new UUIDT().toString()

    const metricBefore = await getMetric({
        name: 'latest_processed_timestamp_ms',
        type: 'GAUGE',
        labels: { topic: 'clickhouse_events_json', partition: '0', groupId: 'async_handlers' },
    })

    await capture({
        teamId,
        distinctId,
        uuid,
        event: '$autocapture',
        properties: {
            name: 'hehe',
            uuid: new UUIDT().toString(),
            $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' }],
        },
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

const createHistoricalExportJob = async ({ teamId, pluginConfigId, dateRange }) => {
    // Queues an historical export for the specified pluginConfigId and date
    // range.
    //
    // NOTE: the frontend doesn't actually push to this queue but rather
    // adds directly to PostgreSQL using the graphile-worker stored
    // procedure `add_job`. I'd rather keep these tests graphile
    // unaware.
    await produce({
        topic: 'jobs',
        message: Buffer.from(
            JSON.stringify({
                type: 'Export historical events V2',
                pluginConfigId: pluginConfigId,
                pluginConfigTeam: teamId,
                payload: {
                    dateRange: dateRange,
                    $job_id: uuid4(),
                    parallelism: 1,
                },
            })
        ),
        key: teamId.toString(),
    })
}
