import { v4 as uuid4 } from 'uuid'

import { ONE_HOUR } from '../src/config/constants'
import { UUIDT } from '../src/utils/utils'
import {
    capture,
    createAndReloadPluginConfig,
    createOrganization,
    createPlugin,
    createTeam,
    fetchEvents,
    fetchPluginLogEntries,
    fetchPostgresPersons,
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
        const logEntries = await fetchPluginLogEntries(pluginConfig.id)
        const onEvent = logEntries.filter(({ message: [method] }) => method === 'onEvent')
        expect(onEvent.length).toBeGreaterThan(0)
        const onEventEvent = onEvent[0].message[1]
        expect(onEventEvent.event).toEqual('custom event')
        expect(onEventEvent.properties).toEqual(expect.objectContaining(event.properties))
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
            const logEntries = await fetchPluginLogEntries(pluginConfig.id)
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
        const logEntries = await fetchPluginLogEntries(pluginConfig.id)
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
        const logEntries = await fetchPluginLogEntries(pluginConfig.id)
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
                const logEntries = await fetchPluginLogEntries(pluginConfig.id)
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
