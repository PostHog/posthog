import ClickHouse from '@posthog/clickhouse'
import Redis from 'ioredis'
import { Kafka, Partitioners, Producer } from 'kafkajs'
import { Pool } from 'pg'

import { defaultConfig } from '../src/config/config'
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

test.concurrent(`plugin method tests: event captured, processed, ingested`, async () => {
    const plugin = await createPlugin(postgres, {
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
    const teamId = await createTeam(postgres, organizationId)
    const pluginConfig = await createAndReloadPluginConfig(postgres, teamId, plugin.id, redis)
    const distinctId = new UUIDT().toString()
    const uuid = new UUIDT().toString()

    const event = {
        event: 'custom event',
        properties: { name: 'haha' },
    }

    await capture(producer, teamId, distinctId, uuid, event.event, event.properties)

    await waitForExpect(async () => {
        const events = await fetchEvents(clickHouseClient, teamId)
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
        const logEntries = await fetchPluginLogEntries(clickHouseClient, pluginConfig.id)
        const onEvent = logEntries.filter(({ message: [method] }) => method === 'onEvent')
        expect(onEvent.length).toBeGreaterThan(0)
        const onEventEvent = onEvent[0].message[1]
        expect(onEventEvent.event).toEqual('custom event')
        expect(onEventEvent.properties).toEqual(expect.objectContaining(event.properties))
    })
})

test.concurrent(`plugin method tests: can update person properties via processEvent`, async () => {
    // Prior to introducing
    // https://github.com/PostHog/product-internal/pull/405/files this was
    // possible so I'm including a test here to explicitly check for it.
    const plugin = await createPlugin(postgres, {
        organization_id: organizationId,
        name: 'test plugin',
        plugin_type: 'source',
        is_global: false,
        source__index_ts: `
            export async function processEvent(event) {
                return {
                    ...event,
                    properties: {
                        ...event.properties,
                        $set: { 
                            property: 'hell yes',
                        }
                    }
                }
            }
        `,
    })
    const teamId = await createTeam(postgres, organizationId)
    await createAndReloadPluginConfig(postgres, teamId, plugin.id, redis)
    const distinctId = new UUIDT().toString()
    const uuid = new UUIDT().toString()

    await capture(producer, teamId, distinctId, uuid, 'custom event')

    await waitForExpect(async () => {
        const events = await fetchEvents(clickHouseClient, teamId, uuid)
        expect(events.length).toBe(1)
        expect(events[0]).toEqual(
            expect.objectContaining({
                person_properties: expect.objectContaining({ property: 'hell yes' }),
            })
        )
    })
})

test.concurrent(
    `plugin method tests: correct $autocapture properties included in onEvent calls`,
    async () => {
        // The plugin server does modifications to the `event.properties`
        // and as a results we remove the initial `$elements` from the
        // object. Thus we want to ensure that this information is passed
        // through to any plugins with `onEvent` handlers
        const plugin = await createPlugin(postgres, {
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
        const teamId = await createTeam(postgres, organizationId)
        const pluginConfig = await createAndReloadPluginConfig(postgres, teamId, plugin.id, redis)

        const distinctId = new UUIDT().toString()
        const uuid = new UUIDT().toString()

        const properties = {
            $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' }],
        }

        const event = {
            event: '$autocapture',
            properties: properties,
        }

        await capture(producer, teamId, distinctId, uuid, event.event, event.properties)

        await waitForExpect(async () => {
            const logEntries = await fetchPluginLogEntries(clickHouseClient, pluginConfig.id)
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

    const plugin = await createPlugin(postgres, {
        organization_id: organizationId,
        name: 'jobs plugin',
        plugin_type: 'source',
        is_global: false,
        source__index_ts: indexJs,
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

    await waitForExpect(async () => {
        const events = await fetchEvents(clickHouseClient, teamId)
        expect(events.length).toBe(1)
    })

    // Then check that the runMeAsync function was called
    await waitForExpect(async () => {
        const logEntries = await fetchPluginLogEntries(clickHouseClient, pluginConfig.id)
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

    const plugin = await createPlugin(postgres, {
        organization_id: organizationId,
        name: 'jobs plugin',
        plugin_type: 'source',
        is_global: false,
        source__index_ts: indexJs,
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

    await waitForExpect(async () => {
        const events = await fetchEvents(clickHouseClient, teamId)
        expect(events.length).toBe(1)
    })

    // Then check that the runMeAsync function was called
    await waitForExpect(async () => {
        const logEntries = await fetchPluginLogEntries(clickHouseClient, pluginConfig.id)
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
        const plugin = await createPlugin(postgres, {
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

        const teamId = await createTeam(postgres, organizationId)
        const pluginConfig = await createAndReloadPluginConfig(postgres, teamId, plugin.id, redis)

        await waitForExpect(
            async () => {
                const logEntries = await fetchPluginLogEntries(clickHouseClient, pluginConfig.id)
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
