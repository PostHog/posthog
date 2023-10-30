import { v4 as uuid4 } from 'uuid'

import { ONE_HOUR } from '../src/config/constants'
import { UUIDT } from '../src/utils/utils'
import {
    capture,
    createAndReloadPluginConfig,
    createOrganization,
    createPlugin,
    createPluginAttachment,
    createPluginConfig,
    createTeam,
    fetchEvents,
    fetchPluginConsoleLogEntries,
    fetchPostgresPersons,
    getPluginConfig,
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

test.concurrent(`plugin method tests: creates error on unhandled throw`, async () => {
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
        // NOTE: Before `sanitizeJsonbValue` was added, the null byte below would blow up the error
        // UPDATE, breaking this test. It is now replaced with the Unicode replacement character,
        // \uFFFD.
        properties: { name: 'haha', other: '\u0000' },
    }

    await capture({ teamId, distinctId, uuid, event: event.event, properties: event.properties })

    await waitForExpect(async () => {
        const events = await fetchEvents(teamId)
        expect(events.length).toBe(1)
        return events
    })

    const error = await waitForExpect(async () => {
        const pluginConfigAgain = await getPluginConfig(teamId, pluginConfig.id)
        expect(pluginConfigAgain.error).not.toBeNull()
        return pluginConfigAgain.error
    })

    expect(error.message).toEqual('error thrown in plugin')
    const errorProperties = error.event.properties
    expect(errorProperties.name).toEqual('haha')
    expect(errorProperties.other).toEqual('\uFFFD')
})

test.concurrent(`plugin method tests: creates error on unhandled rejection`, async () => {
    const plugin = await createPlugin({
        organization_id: organizationId,
        name: 'test plugin',
        plugin_type: 'source',
        is_global: false,
        source__index_ts: `
            export async function processEvent(event) {
                void new Promise((_, rejects) => { rejects(new Error('error thrown in plugin')) }).then(() => {})
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

    const error = await waitForExpect(async () => {
        const pluginConfigAgain = await getPluginConfig(teamId, pluginConfig.id)
        expect(pluginConfigAgain.error).not.toBeNull()
        return pluginConfigAgain.error
    })

    expect(error.message).toEqual('error thrown in plugin')
})

test.concurrent(`plugin method tests: creates error on unhandled promise errors`, async () => {
    const plugin = await createPlugin({
        organization_id: organizationId,
        name: 'test plugin',
        plugin_type: 'source',
        is_global: false,
        source__index_ts: `
            export async function processEvent(event) {
                void new Promise(() => { throw new Error('error thrown in plugin') }).then(() => {})
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

    const error = await waitForExpect(async () => {
        const pluginConfigAgain = await getPluginConfig(teamId, pluginConfig.id)
        expect(pluginConfigAgain.error).not.toBeNull()
        return pluginConfigAgain.error
    })

    expect(error.message).toEqual('error thrown in plugin')
})

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
                console.log({ method: "teardownPlugin" })
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

    await waitForExpect(async () => {
        const logs = await fetchPluginConsoleLogEntries(pluginConfig.id)
        expect(logs.filter((log) => log.message.method === 'teardownPlugin')).toHaveLength(1)
    })
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

        await capture({ teamId, distinctId, uuid, event: event.event, properties: event.properties })

        await waitForExpect(async () => {
            const logEntries = await fetchPluginConsoleLogEntries(pluginConfig.id)
            const onEvent = logEntries.filter(({ message: [method] }) => method === 'onEvent')
            expect(onEvent.length).toBeGreaterThan(0)

            const onEventEvent = onEvent[0].message[1]
            expect(onEventEvent.elements).toEqual([
                expect.objectContaining({
                    attributes: {},
                    nth_child: 1,
                    nth_of_type: 2,
                    tag_name: 'div',
                    text: '💻',
                }),
            ])
        })
    },
    20000
)

test.concurrent(`plugin jobs: can call runNow from onEvent`, async () => {
    const indexJs = `
        export function onEvent (event, { jobs }) {
            console.info(JSON.stringify(['onEvent', event]))
            jobs.runMeAsync().runNow()
        }

        export const jobs = {
            runMeAsync: async () => {
                console.info(JSON.stringify(['runMeAsync']))
            }
        }
    `

    const plugin = await createPlugin({
        organization_id: organizationId,
        name: 'jobs plugin',
        plugin_type: 'source',
        is_global: false,
        source__index_ts: indexJs,
    })
    const teamId = await createTeam(organizationId)
    const pluginConfig = await createAndReloadPluginConfig(teamId, plugin.id)
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

    await waitForExpect(async () => {
        const events = await fetchEvents(teamId)
        expect(events.length).toBe(1)
    })

    // Then check that the runMeAsync function was called
    await waitForExpect(async () => {
        const logEntries = await fetchPluginConsoleLogEntries(pluginConfig.id)
        const runMeAsync = logEntries.filter(({ message: [method] }) => method === 'runMeAsync')
        expect(runMeAsync.length).toBeGreaterThan(0)
    })
})

test.concurrent(`plugin jobs: can call runNow from processEvent`, async () => {
    const indexJs = `
        export function processEvent(event, { jobs }) {
            console.info(JSON.stringify(['processEvent', event]))
            jobs.runMeAsync().runNow()
            return event
        }

        export const jobs = {
            runMeAsync: async () => {
                console.info(JSON.stringify(['runMeAsync']))
            }
        }
    `

    const plugin = await createPlugin({
        organization_id: organizationId,
        name: 'jobs plugin',
        plugin_type: 'source',
        is_global: false,
        source__index_ts: indexJs,
    })
    const teamId = await createTeam(organizationId)
    const pluginConfig = await createAndReloadPluginConfig(teamId, plugin.id)
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

    await waitForExpect(async () => {
        const events = await fetchEvents(teamId)
        expect(events.length).toBe(1)
    })

    // Then check that the runMeAsync function was called
    await waitForExpect(async () => {
        const logEntries = await fetchPluginConsoleLogEntries(pluginConfig.id)
        const runMeAsync = logEntries.filter(({ message: [method] }) => method === 'runMeAsync')
        expect(runMeAsync.length).toBeGreaterThan(0)
    })
})

test.concurrent(
    `plugin jobs: runEveryMinute is executed`,
    async () => {
        // NOTE: we do not check Hour and Day, merely because if we advance
        // too much it seems we end up performing alot of reloads of
        // actions, which prevents the test from completing.
        //
        // NOTE: we do not use Fake Timers here as there is an issue in that
        // it only appears to work for timers in the main thread, and not
        // ones in the worker threads.
        const plugin = await createPlugin({
            organization_id: organizationId,
            name: 'runEveryMinute plugin',
            plugin_type: 'source',
            is_global: false,
            source__index_ts: `
            export async function runEveryMinute() {
                console.info(JSON.stringify(['runEveryMinute']))
            }
        `,
        })

        const teamId = await createTeam(organizationId)
        const pluginConfig = await createAndReloadPluginConfig(teamId, plugin.id)

        await waitForExpect(
            async () => {
                const logEntries = await fetchPluginConsoleLogEntries(pluginConfig.id)
                expect(
                    logEntries.filter(({ message: [method] }) => method === 'runEveryMinute').length
                ).toBeGreaterThan(0)
            },
            120_000,
            1000
        )
    },
    120000
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

    const pluginConfig = await createPluginConfig({ team_id: teamId, plugin_id: plugin.id, config: {} })
    await createPluginAttachment({
        teamId,
        pluginConfigId: pluginConfig.id,
        fileSize: 4,
        contentType: 'text/plain',
        fileName: 'test.txt',
        key: 'testAttachment',
        contents: 'test',
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
