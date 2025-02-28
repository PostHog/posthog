import { v4 as uuid4 } from 'uuid'

import { ONE_HOUR } from '../src/config/constants'
import { PluginLogEntryType } from '../src/types'
import { UUIDT } from '../src/utils/utils'
import { getCacheKey } from '../src/worker/vm/extensions/cache'
import {
    capture,
    createAndReloadPluginConfig,
    createOrganization,
    createPlugin,
    createPluginAttachment,
    createPluginConfig,
    createTeam,
    enablePluginConfig,
    fetchEvents,
    fetchPluginAppMetrics,
    fetchPluginConsoleLogEntries,
    fetchPluginLogEntries,
    fetchPostgresPersons,
    getPluginConfig,
    redis,
    reloadPlugins,
    updatePluginConfig,
    waitForPluginToLoad,
} from './api'
import { waitForExpect } from './expectations'

let organizationId: string

beforeAll(async () => {
    organizationId = await createOrganization()
})

test.concurrent(`plugin method tests: event captured, processed, ingested`, async () => {
    const plugin = await createPlugin({
        organization_id: organizationId,
        name: 'test plugin',
        plugin_type: 'source',
        is_global: false,
        source__index_ts: `
            export async function processEvent(event) {
                event.properties.processed = 'hell yes'
                event.properties.upperUuid = event.properties.uuid?.toUpperCase()
                event.properties['$snapshot_data'] = 'no way'
                event.properties.runCount = (event.properties.runCount || 0) + 1
                return event
            }

            export function onEvent (event, { global }) {
                // we use this to mock setupPlugin being
                // run after some events were already ingested
                global.timestampBoundariesForTeam = {
                    max: new Date(),
                    min: new Date(Date.now()-${ONE_HOUR})
                }
                console.info(JSON.stringify(['onEvent', event]))
            }
        `,
    })
    const teamId = await createTeam(organizationId)
    const pluginConfig = await createAndReloadPluginConfig(teamId, plugin.id)
    const distinctId = new UUIDT().toString()
    const uuid = new UUIDT().toString()

    const event = {
        event: 'custom event',
        properties: { name: 'haha' },
    }

    await capture({ teamId, distinctId, uuid, event: event.event, properties: event.properties })

    await waitForExpect(async () => {
        const events = await fetchEvents(teamId)
        expect(events.length).toBe(1)
        expect(events[0].properties).toEqual(
            expect.objectContaining({
                processed: 'hell yes',
                upperUuid: uuid.toUpperCase(),
                runCount: 1,
            })
        )
    })

    // onEvent ran
    await waitForExpect(async () => {
        const logEntries = await fetchPluginConsoleLogEntries(pluginConfig.id)
        const onEvent = logEntries.filter(({ message: [method] }) => method === 'onEvent')
        expect(onEvent.length).toBeGreaterThan(0)
        const onEventEvent = onEvent[0].message[1]
        expect(onEventEvent.event).toEqual('custom event')
        expect(onEventEvent.properties).toEqual(expect.objectContaining(event.properties))
    })
})

test.concurrent(
    `plugin method tests: records error in app metrics and creates log entry on unhandled throw`,
    async () => {
        const plugin = await createPlugin({
            organization_id: organizationId,
            name: 'test plugin',
            plugin_type: 'source',
            is_global: false,
            source__index_ts: `
            export async function processEvent(event) {
                throw new Error('error thrown in plugin')
            }
        `,
        })
        const teamId = await createTeam(organizationId)
        const pluginConfig = await createAndReloadPluginConfig(teamId, plugin.id)

        const distinctId = new UUIDT().toString()
        const uuid = new UUIDT().toString()

        const event = {
            event: 'custom event',
            properties: { name: 'haha', other: '\u0000' },
        }

        await capture({ teamId, distinctId, uuid, event: event.event, properties: event.properties })

        await waitForExpect(async () => {
            const events = await fetchEvents(teamId)
            expect(events.length).toBe(1)
            return events
        })

        const appMetric = await waitForExpect(async () => {
            const errorMetrics = await fetchPluginAppMetrics(pluginConfig.id)
            expect(errorMetrics.length).toEqual(1)
            return errorMetrics[0]
        })

        expect(appMetric.successes).toEqual(0)
        expect(appMetric.failures).toEqual(1)
        expect(appMetric.error_type).toEqual('Error')
        expect(JSON.parse(appMetric.error_details!)).toMatchObject({
            error: { message: 'error thrown in plugin' },
            event: { properties: event.properties },
        })

        const errorLogEntry = await waitForExpect(async () => {
            const errorLogEntries = (await fetchPluginLogEntries(pluginConfig.id)).filter(
                (entry) => entry.type == PluginLogEntryType.Error
            )
            expect(errorLogEntries.length).toBe(1)
            return errorLogEntries[0]
        })

        expect(errorLogEntry.message).toContain('error thrown in plugin')
    }
)

test.concurrent(
    `plugin method tests: records success in app metrics and creates error log entry on unawaited promise rejection`,
    async () => {
        const plugin = await createPlugin({
            organization_id: organizationId,
            name: 'test plugin',
            plugin_type: 'source',
            is_global: false,
            source__index_ts: `
            export async function processEvent(event) {
                void new Promise(() => { throw new Error('error thrown in plugin') })
                return event
            }
        `,
        })
        const teamId = await createTeam(organizationId)
        const pluginConfig = await createAndReloadPluginConfig(teamId, plugin.id)

        const distinctId = new UUIDT().toString()
        const uuid = new UUIDT().toString()

        const event = {
            event: 'custom event',
            properties: { name: 'haha' },
        }

        await capture({ teamId, distinctId, uuid, event: event.event, properties: event.properties })

        await waitForExpect(async () => {
            const events = await fetchEvents(teamId)
            expect(events.length).toBe(1)
            return events
        })

        const appMetric = await waitForExpect(async () => {
            const appMetrics = await fetchPluginAppMetrics(pluginConfig.id)
            expect(appMetrics.length).toEqual(1)
            return appMetrics[0]
        })

        expect(appMetric.successes).toEqual(1)
        expect(appMetric.failures).toEqual(0)

        const errorLogEntry = await waitForExpect(async () => {
            const errorLogEntries = (await fetchPluginLogEntries(pluginConfig.id)).filter(
                (entry) => entry.type == PluginLogEntryType.Error
            )
            expect(errorLogEntries.length).toBe(1)
            return errorLogEntries[0]
        })

        expect(errorLogEntry.message).toContain('error thrown in plugin')
    }
)

test.concurrent(`plugin method tests: teardown is called on stateful plugin reload if they are updated`, async () => {
    const plugin = await createPlugin({
        organization_id: organizationId,
        name: 'test plugin',
        plugin_type: 'source',
        is_global: false,
        is_stateless: false,
        source__index_ts: `
            async function processEvent (event, meta) {
                console.log({ method: "processEvent" })
                return event
            }

            async function teardownPlugin(meta) {
                await meta.cache.lpush("teardown", "x")
            }
        `,
    })

    const teamId = await createTeam(organizationId)
    const pluginConfig = await createAndReloadPluginConfig(teamId, plugin.id)

    const distinctId = new UUIDT().toString()
    const uuid = new UUIDT().toString()

    const event = {
        event: 'custom event',
        properties: { name: 'haha' },
    }

    await capture({ teamId, distinctId, uuid, event: event.event, properties: event.properties })

    await waitForExpect(async () => {
        const events = await fetchEvents(teamId)
        expect(events.length).toBe(1)
    })

    const pluginConfigAgain = await getPluginConfig(teamId, pluginConfig.id)
    expect(pluginConfigAgain.error).toBeNull()

    // We need to first change the plugin config to trigger a reload of the plugin.
    await updatePluginConfig(teamId, pluginConfig.id, { updated_at: new Date().toISOString() })
    await reloadPlugins()

    const signalKey = getCacheKey(plugin.id, teamId, 'teardown')
    expect(await redis.blpop(signalKey, 10)).toEqual([signalKey, 'x'])
})

test.concurrent(`plugin method tests: can update distinct_id via processEvent`, async () => {
    // Prior to introducing
    // https://github.com/PostHog/product-internal/pull/405/files this was
    // possible so I'm including a test here to explicitly check for it.
    const plugin = await createPlugin({
        organization_id: organizationId,
        name: 'test plugin',
        plugin_type: 'source',
        is_global: false,
        source__index_ts: `
            export async function processEvent(event) {
                return {
                    ...event,
                    distinct_id: 'hell yes'
                }
            }
        `,
    })
    const teamId = await createTeam(organizationId)
    await createAndReloadPluginConfig(teamId, plugin.id)
    const distinctId = new UUIDT().toString()
    const uuid = new UUIDT().toString()

    await capture({ teamId, distinctId, uuid, event: 'custom event' })

    await waitForExpect(async () => {
        const events = await fetchEvents(teamId, uuid)
        expect(events.length).toBe(1)
        expect(events[0]).toEqual(
            expect.objectContaining({
                distinct_id: 'hell yes',
            })
        )
    })
})

test.concurrent(`plugin method tests: can drop events via processEvent`, async () => {
    // Plugins should be able to specify that some events are now ingested
    const plugin = await createPlugin({
        organization_id: organizationId,
        name: 'test plugin',
        plugin_type: 'source',
        is_global: false,
        source__index_ts: `
            export async function processEvent(event) {
                return event.event === 'drop me' ? null : event
            }
        `,
    })
    const teamId = await createTeam(organizationId)
    await createAndReloadPluginConfig(teamId, plugin.id)
    const aliceId = new UUIDT().toString()
    const bobId = new UUIDT().toString()

    // First capture the event we want to drop
    const dropMeUuid = new UUIDT().toString()
    await capture({ teamId, distinctId: aliceId, uuid: dropMeUuid, event: 'drop me' })

    // Then capture a custom event that will not be dropped. We capture this
    // second such that if we have ingested this event, we can be reasonably
    // confident that the drop me event was also completely processed.
    const customEventUuid = uuid4()
    await capture({ teamId, distinctId: bobId, uuid: customEventUuid, event: 'custom event' })

    await waitForExpect(async () => {
        const [event] = await fetchEvents(teamId, customEventUuid)
        expect(event).toBeDefined()
    })

    const [event] = await fetchEvents(teamId, dropMeUuid)
    expect(event).toBeUndefined()

    // Further, only the custom events should produce persons
    const persons = await fetchPostgresPersons(teamId)
    expect(persons.length).toBe(1)
})

test.concurrent(
    `plugin method tests: correct $autocapture properties included in onEvent calls`,
    async () => {
        // The plugin server does modifications to the `event.properties`
        // and as a results we remove the initial `$elements` from the
        // object. Thus we want to ensure that this information is passed
        // through to any plugins with `onEvent` handlers
        const plugin = await createPlugin({
            organization_id: organizationId,
            name: 'test plugin',
            plugin_type: 'source',
            is_global: false,
            source__index_ts: `
            export async function processEvent(event) {
                event.properties.processed = 'hell yes'
                event.properties.upperUuid = event.properties.uuid?.toUpperCase()
                event.properties['$snapshot_data'] = 'no way'
                return event
            }

            export function onEvent (event, { global }) {
                // we use this to mock setupPlugin being
                // run after some events were already ingested
                global.timestampBoundariesForTeam = {
                    max: new Date(),
                    min: new Date(Date.now()-${ONE_HOUR})
                }
                console.info(JSON.stringify(['onEvent', event]))
            }
        `,
        })
        const teamId = await createTeam(organizationId)
        const pluginConfig = await createAndReloadPluginConfig(teamId, plugin.id)

        const distinctId = new UUIDT().toString()
        const uuid = new UUIDT().toString()

        const properties = {
            $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' }],
        }

        const event = {
            event: '$autocapture',
            properties: properties,
        }

        await waitForExpect(async () => {
            // We might have not completed the setup properly in time, so to avoid flaky tests, we'll
            // try sending messages and checking the last log message until we get the expected result.
            await capture({ teamId, distinctId, uuid, event: event.event, properties: event.properties })
            const logEntries = await fetchPluginConsoleLogEntries(pluginConfig.id)
            const onEvent = logEntries.filter(({ message: [method] }) => method === 'onEvent')
            const lastLogEntry = onEvent.length > 0 ? onEvent[onEvent.length - 1] : null
            expect(lastLogEntry).toEqual(
                expect.objectContaining({
                    message: [
                        'onEvent',
                        expect.objectContaining({
                            elements: [
                                expect.objectContaining({
                                    attributes: {},
                                    nth_child: 1,
                                    nth_of_type: 2,
                                    tag_name: 'div',
                                    text: '💻',
                                }),
                            ],
                        }),
                    ],
                })
            )
        })
    },
    20000
)

test.concurrent('plugins can use attachements', async () => {
    const indexJs = `
        export function processEvent(event, { attachments }) {
            return {
                ...event,
                properties: {
                    ...event.properties,
                    attachments: attachments
                }
            };
        }`

    const teamId = await createTeam(organizationId)
    const plugin = await createPlugin({
        organization_id: organizationId,
        name: 'attachments plugin',
        plugin_type: 'source',
        is_global: false,
        source__index_ts: indexJs,
    })

    // Create the pluginconfig disabled to avoid it being loaded by a concurrent test
    // before the attachment is available.
    const pluginConfig = await createPluginConfig({ team_id: teamId, plugin_id: plugin.id, config: {} }, false)
    await createPluginAttachment({
        teamId,
        pluginConfigId: pluginConfig.id,
        fileSize: 4,
        contentType: 'text/plain',
        fileName: 'test.txt',
        key: 'testAttachment',
        contents: 'test',
    })
    await enablePluginConfig(teamId, pluginConfig.id)

    await reloadPlugins()

    // Wait for plugin setupPlugin to have run
    await waitForPluginToLoad(pluginConfig)

    const distinctId = new UUIDT().toString()
    const uuid = new UUIDT().toString()

    // Wait for

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

    const [event] = await waitForExpect(async () => {
        const events = await fetchEvents(teamId)
        expect(events.length).toBe(1)
        return events
    })

    // Check the attachment was added to the event.
    expect(event.properties.attachments).toEqual({
        testAttachment: {
            file_name: 'test.txt',
            content_type: 'text/plain',
            contents: JSON.parse(JSON.stringify(Buffer.from('test'))),
        },
    })
})

test.concurrent('plugins can use config variables', async () => {
    const indexJs = `
        export function processEvent(event, { config }) {
            return {
                ...event,
                properties: {
                    ...event.properties,
                    config: config
                }
            };
        }`

    const pluginJson = {
        name: 'plugin with secret',
        url: 'https://some.url',
        description: '',
        main: 'index.js',
        config: [
            {
                markdown: 'A Markdown block.\n[Use links](http://example.com) and other goodies!',
            },
            {
                key: 'secretVariable',
                name: 'Secret Variable',
                type: 'string',
                default: '',
                hint: '',
                required: true,
                secret: true,
            },
            {
                key: 'normalVariable',
                name: 'Normal Variable',
                type: 'string',
                default: '',
                hint: '',
            },
        ],
    }

    const teamId = await createTeam(organizationId)
    const plugin = await createPlugin({
        organization_id: organizationId,
        name: 'plugin config',
        plugin_type: 'source',
        is_global: false,
        source__index_ts: indexJs,
        source__plugin_json: JSON.stringify(pluginJson),
    })

    const pluginConfig = await createPluginConfig({
        team_id: teamId,
        plugin_id: plugin.id,
        config: { secretVariable: 'super secret', normalVariable: 'look at me' },
    })
    await reloadPlugins()

    // Wait for plugin setupPlugin to have run
    await waitForPluginToLoad(pluginConfig)

    const distinctId = new UUIDT().toString()
    const uuid = new UUIDT().toString()

    // Wait for

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

    const [event] = await waitForExpect(async () => {
        const events = await fetchEvents(teamId)
        expect(events.length).toBe(1)
        return events
    })

    // Check the attachment was added to the event.
    expect(event.properties.config).toEqual({
        secretVariable: 'super secret',
        normalVariable: 'look at me',
    })
})

test.concurrent(
    'plugin configs are still loaded if is_global = false and the team does not own the plugin',
    async () => {
        // The is mainly to verify that we can make plugins non-global without
        // breaking existing pluginconfigs.
        const indexJs = `
        export function processEvent(event) {
            return {
                ...event,
                properties: {
                    ...event.properties,
                    processed: true
                }
            };
        }`

        const plugin = await createPlugin({
            organization_id: organizationId,
            name: 'plugin config',
            plugin_type: 'source',
            is_global: false,
            source__index_ts: indexJs,
        })

        // Create a plugin config that is in a different organization
        const otherOrganizationId = await createOrganization()
        const otherTeamId = await createTeam(otherOrganizationId)
        const otherPluginConfig = await createPluginConfig({
            team_id: otherTeamId,
            plugin_id: plugin.id,
            config: {},
        })

        await reloadPlugins()
        await waitForPluginToLoad(otherPluginConfig)

        const distinctId = new UUIDT().toString()
        const uuid = new UUIDT().toString()

        // First let's ingest an event
        await capture({
            teamId: otherTeamId,
            distinctId,
            uuid,
            event: 'custom event',
            properties: {
                name: 'hehe',
                uuid: new UUIDT().toString(),
            },
        })

        const [event] = await waitForExpect(async () => {
            const events = await fetchEvents(otherTeamId)
            expect(events.length).toBe(1)
            return events
        })

        // Check it was processed
        expect(event.properties.processed).toEqual(true)
    }
)

test.concurrent(`liveness check endpoint works`, async () => {
    await waitForExpect(async () => {
        const response = await fetch('http://localhost:6738/_health')
        expect(response.status).toBe(200)

        const body = await response.json()
        expect(body).toEqual(
            expect.objectContaining({
                checks: expect.objectContaining({ 'on-event-ingestion': 'ok' }),
            })
        )
    })
})
