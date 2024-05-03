import { createServer, Server } from 'http'

import { UUIDT } from '../src/utils/utils'
import { capture, createAndReloadPluginConfig, createOrganization, createPlugin, createTeam } from './api'
import { waitForExpect } from './expectations'

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
            export const onEvent = async (event, { global, config }) => {
                await fetch(
                    "http://localhost:${server.address()?.port}/${teamId}", 
                    {method: "POST", body: JSON.stringify(event)}
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

    // Then check that the onEvent function was called
    await waitForExpect(
        () => {
            const onEvents = webHookCalledWith[`/${teamId}`]
            expect(onEvents).toEqual([
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

test.concurrent.skip(`exports: exporting $autocapture events on ingestion`, async () => {
    const teamId = await createTeam(organizationId)
    const plugin = await createPlugin({
        organization_id: organizationId,
        name: 'export plugin',
        plugin_type: 'source',
        is_global: false,
        source__index_ts: `
            export const onEvent = async (event, { global, config }) => {
                await fetch(
                    "http://localhost:${server.address()?.port}/${teamId}", 
                    {method: "POST", body: JSON.stringify(event)}
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

    // Then check that the onEvent function was called
    await waitForExpect(
        () => {
            const onEvents = webHookCalledWith[`/${teamId}`]
            expect(onEvents).toEqual([
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
