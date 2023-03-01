import { createServer, Server } from 'http'

import { UUIDT } from '../src/utils/utils'
import { capture, createAndReloadPluginConfig, createOrganization, createPlugin, createTeam } from './api'
import { waitForExpect } from './expectations'
import { produce } from './kafka'

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

test.concurrent(`exports: exporting events on ingestion`, async () => {
    const teamId = await createTeam(organizationId)
    const plugin = await createPlugin({
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
    await createAndReloadPluginConfig(teamId, plugin.id)
    const distinctId = new UUIDT().toString()
    const uuid = new UUIDT().toString()

    // First let's ingest an event
    await capture({
        teamId,
        distinctId,
        uuid,
        event: 'custom event',
        properties: {
            name: 'hehe',
            uuid: new UUIDT().toString(),
        },
    })

    // Then check that the exportEvents function was called
    await waitForExpect(
        () => {
            const exportEvents = webHookCalledWith[`/${teamId}`]
            expect(exportEvents.length).toBeGreaterThan(0)
            const exportedEvents = exportEvents[0]

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
        },
        60_000,
        1_000
    )
})

test.concurrent(`exports: exporting $autocapture events on ingestion`, async () => {
    const teamId = await createTeam(organizationId)
    const plugin = await createPlugin({
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

    await createAndReloadPluginConfig(teamId, plugin.id)
    const distinctId = new UUIDT().toString()
    const uuid = new UUIDT().toString()

    // First let's ingest an event
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

    // Then check that the exportEvents function was called
    await waitForExpect(
        () => {
            const exportEvents = webHookCalledWith[`/${teamId}`]
            expect(exportEvents.length).toBeGreaterThan(0)
            const exportedEvents = exportEvents[0]
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
        },
        60_000,
        1_000
    )
})

test.concurrent(`exports: historical exports`, async () => {
    const teamId = await createTeam(organizationId)
    const distinctId = new UUIDT().toString()
    const uuid = new UUIDT().toString()

    const plugin = await createPlugin({
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
    const pluginConfig = await createAndReloadPluginConfig(teamId, plugin.id)

    // First let's capture an event and wait for it to be ingested so
    // so we can check that the historical event is the same as the one
    // passed to processEvent on initial ingestion.
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

    // Then check that the exportEvents function was called
    const [exportedEvent] = await waitForExpect(
        () => {
            const exportEvents = webHookCalledWith[`/${teamId}`]
            expect(exportEvents.length).toBeGreaterThan(0)
            return exportEvents[0]
        },
        60_000,
        1_000
    )

    // NOTE: the frontend doesn't actually push to this queue but rather
    // adds directly to PostgreSQL using the graphile-worker stored
    // procedure `add_job`. I'd rather keep these tests graphile
    // unaware.
    await produce({
        topic: 'jobs',
        message: Buffer.from(
            JSON.stringify({
                type: 'Export historical events',
                pluginConfigId: pluginConfig.id,
                pluginConfigTeam: teamId,
                payload: {
                    dateFrom: new Date(Date.now() - 60000).toISOString(),
                    dateTo: new Date(Date.now()).toISOString(),
                },
            })
        ),
        key: teamId.toString(),
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

            const historicallyExportedEvent = historicallyExportedEvents[0]
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
        },
        60_000,
        1_000
    )
})
