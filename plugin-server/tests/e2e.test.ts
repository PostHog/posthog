import ClickHouse from '@posthog/clickhouse'
import Redis from 'ioredis'
import { Kafka, Partitioners, Producer } from 'kafkajs'
import { Pool } from 'pg'

import { defaultConfig } from '../src/config/config'
import { ONE_HOUR } from '../src/config/constants'
import { ServerInstance, startPluginsServer } from '../src/main/pluginsServer'
import {
    LogLevel,
    PluginLogEntry,
    PluginsServerConfig,
    RawClickHouseEvent,
    RawPerson,
    RawSessionRecordingEvent,
} from '../src/types'
import { Plugin, PluginConfig } from '../src/types'
import { parseRawClickHouseEvent } from '../src/utils/event'
import { UUIDT } from '../src/utils/utils'
import { delayUntilEventIngested } from './helpers/clickhouse'
import { insertRow, POSTGRES_TRUNCATE_TABLES_QUERY } from './helpers/sql'

jest.setTimeout(60000) // 60 sec timeout

const extraServerConfig: Partial<PluginsServerConfig> = {
    WORKER_CONCURRENCY: 1,
    LOG_LEVEL: LogLevel.Log,
    // Conversion buffer is now default enabled, so we should enable it for
    // tests.
    CONVERSION_BUFFER_ENABLED: true,
    // Enable buffer topic for all teams. We are already testing the legacy
    // functionality in `e2e.buffer.test.ts`, which we can remove once we've
    // completely switched over.
    CONVERSION_BUFFER_TOPIC_ENABLED_TEAMS: '*',
    // To enable the tests for person on events to work as expected, we need to
    // add a slight delay.
    BUFFER_CONVERSION_SECONDS: 2,
    // Make sure producer flushes for each message immediately. Note that this
    // does mean that we are not testing the async nature of the producer by
    // doing this.
    // TODO: update producer queueMessage functionality to have flush run async
    // even if the queue is full and flush needs to be called.
    KAFKA_MAX_MESSAGE_BATCH_SIZE: 0,
}

const startMultiServer = async () => {
    // All capabilities run as separate servers
    const ingestionServer = startPluginsServer({ ...extraServerConfig, PLUGIN_SERVER_MODE: 'ingestion' })
    const asyncServer = startPluginsServer({ ...extraServerConfig, PLUGIN_SERVER_MODE: 'async-worker' })
    const jobsServer = startPluginsServer({ ...extraServerConfig, PLUGIN_SERVER_MODE: 'jobs' })
    const schedulerServer = startPluginsServer({ ...extraServerConfig, PLUGIN_SERVER_MODE: 'scheduler' })

    return await Promise.all([ingestionServer, asyncServer, jobsServer, schedulerServer])
}

const startIngestionAsyncSplit = async () => {
    // A split of ingestion and all other tasks
    const ingestionServer = startPluginsServer({ ...extraServerConfig, PLUGIN_SERVER_MODE: 'ingestion' })
    const asyncServer = startPluginsServer({ ...extraServerConfig, PLUGIN_SERVER_MODE: 'async' })

    return await Promise.all([ingestionServer, asyncServer])
}

const startSingleServer = async () => {
    return [await startPluginsServer(extraServerConfig)]
}

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
    await postgres.query(POSTGRES_TRUNCATE_TABLES_QUERY)
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

describe.each([[startSingleServer], [startMultiServer], [startIngestionAsyncSplit]])('E2E', (pluginServer) => {
    let pluginsServers: ServerInstance[]

    beforeAll(async () => {
        pluginsServers = await pluginServer()
    })

    afterAll(async () => {
        await Promise.all(pluginsServers.map((instance) => instance.stop()))
    })

    describe(`plugin method tests (${pluginServer.name})`, () => {
        const indexJs = `
            export async function processEvent (event) {
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
        `

        test.concurrent(
            'event captured, processed, ingested',
            async () => {
                const plugin = await createPlugin(postgres, {
                    organization_id: organizationId,
                    name: 'test plugin',
                    plugin_type: 'source',
                    is_global: false,
                    source__index_ts: indexJs,
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

                await delayUntilEventIngested(() => fetchEvents(clickHouseClient, teamId), 1, 500, 40)
                const events = await fetchEvents(clickHouseClient, teamId)
                expect(events.length).toBe(1)

                // processEvent ran and modified
                expect(events[0].properties.processed).toEqual('hell yes')
                expect(events[0].properties.upperUuid).toEqual(uuid.toUpperCase())

                // onEvent ran
                const onEvent = await delayUntilEventIngested(
                    async () =>
                        (
                            await fetchPluginLogEntries(clickHouseClient, pluginConfig.id)
                        ).filter(({ message: [method] }) => method === 'onEvent'),
                    1,
                    500,
                    40
                )

                expect(onEvent.length).toBeGreaterThan(0)

                const onEventEvent = onEvent[0].message[1]
                expect(onEventEvent.event).toEqual('custom event')
                expect(onEventEvent.properties).toEqual(expect.objectContaining(event.properties))
            },
            10000
        )

        test.concurrent(
            'correct $autocapture properties included in onEvent calls',
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
                    source__index_ts: indexJs,
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

                const onEvent = await delayUntilEventIngested(
                    async () =>
                        (
                            await fetchPluginLogEntries(clickHouseClient, pluginConfig.id)
                        ).filter(({ message: [method] }) => method === 'onEvent'),
                    1,
                    500,
                    40
                )

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
            },
            10000
        )
    })

    describe(`session recording ingestion (${pluginServer.name})`, () => {
        test.concurrent(
            'snapshot captured, processed, ingested',
            async () => {
                const teamId = await createTeam(postgres, organizationId)
                const distinctId = new UUIDT().toString()
                const uuid = new UUIDT().toString()

                await capture(producer, teamId, distinctId, uuid, '$snapshot', {
                    $session_id: '1234abc',
                    $snapshot_data: 'yes way',
                })

                await delayUntilEventIngested(() => fetchSessionRecordingsEvents(clickHouseClient, teamId), 1, 500, 40)
                const events = await fetchSessionRecordingsEvents(clickHouseClient, teamId)
                expect(events.length).toBe(1)

                // processEvent did not modify
                expect(events[0].snapshot_data).toEqual('yes way')
            },
            10000
        )
    })

    describe(`event ingestion (${pluginServer.name})`, () => {
        test.concurrent('anonymous event recieves same person_id if $identify happenes shortly after', async () => {
            // NOTE: this test depends on there being a delay between the
            // anonymouse event ingestion and the processing of this event.
            const teamId = await createTeam(postgres, organizationId)
            const initialDistinctId = 'initialDistinctId'
            const returningDistinctId = 'returningDistinctId'
            const personIdentifier = 'test@posthog.com'

            // First we identify the user using an initial distinct id. After
            // which we capture an event with a different distinct id, then
            // identify this user again with the same person identifier.
            //
            // This is to simulate the case where:
            //
            //  1. user signs up initially, creating a person
            //  2. user returns but as an anonymous user, capturing events
            //  3. user identifies themselves, for instance by logging in
            //
            // In this case we want to end up with on Person to which all the
            // events are associated.

            await capture(producer, teamId, personIdentifier, new UUIDT().toString(), '$identify', {
                distinct_id: personIdentifier,
                $anon_distinct_id: initialDistinctId,
            })

            await capture(producer, teamId, returningDistinctId, new UUIDT().toString(), 'custom event', {
                name: 'hehe',
                uuid: new UUIDT().toString(),
            })

            await new Promise((resolve) => setTimeout(resolve, 100))

            await capture(producer, teamId, personIdentifier, new UUIDT().toString(), '$identify', {
                distinct_id: personIdentifier,
                $anon_distinct_id: returningDistinctId,
            })

            await delayUntilEventIngested(() => fetchEvents(clickHouseClient, teamId), 3, 500, 40)
            const events = await fetchEvents(clickHouseClient, teamId)
            expect(new Set(events.map((event) => event.person_id)).size).toBe(1)

            await delayUntilEventIngested(() => fetchPersons(clickHouseClient, teamId), 1, 500, 40)
            const persons = await fetchPersons(clickHouseClient, teamId)
            expect(persons.length).toBe(1)
        })
    })

    describe(`exports (${pluginServer.name})`, () => {
        const indexJs = `
            export const exportEvents = async (events, { global, config }) => {
                console.info(JSON.stringify(['exportEvents', events]))
            }
        `

        test.concurrent('exporting events', async () => {
            const plugin = await createPlugin(postgres, {
                organization_id: organizationId,
                name: 'export plugin',
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

            await delayUntilEventIngested(() => fetchEvents(clickHouseClient, teamId), 1, 500, 40)

            const events = await fetchEvents(clickHouseClient, teamId)
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
    })

    describe(`plugin jobs (${pluginServer.name})`, () => {
        const indexJs = `    
            export function onEvent (event) {
                console.info(JSON.stringify(['onEvent', event]))
                jobs.runMeAsync().runNow()
            }

            export const jobs = {
                runMeAsync: async () => {
                    console.info(JSON.stringify(['runMeAsync']))
                }
            }
        `

        test.concurrent('runNow', async () => {
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

            await delayUntilEventIngested(() => fetchEvents(clickHouseClient, teamId), 1, 500, 40)

            const events = await fetchEvents(clickHouseClient, teamId)
            expect(events.length).toBe(1)

            // Then check that the runNow function was called
            const runNow = await delayUntilEventIngested(
                async () =>
                    (
                        await fetchPluginLogEntries(clickHouseClient, pluginConfig.id)
                    ).filter(({ message: [method] }) => method === 'runMeAsync'),
                1,
                500,
                40
            )

            expect(runNow.length).toBeGreaterThan(0)
        })

        test.concurrent(
            'runEveryMinute is executed',
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

                const runNow = await delayUntilEventIngested(
                    async () =>
                        (
                            await fetchPluginLogEntries(clickHouseClient, pluginConfig.id)
                        ).filter(({ message: [method] }) => method === 'runEveryMinute'),
                    1,
                    1000,
                    60
                )

                expect(runNow.length).toBeGreaterThan(0)
            },
            60000
        )
    })

    describe(`scheduled tasks (${pluginServer.name})`, () => {
        // KLUDGE: Ideally this test would ensure that the scheduled tasks get called.
        // However, it's very hard to test for this without actually waiting for a minute+
        // to pass in the tests, as messing with Graphile Worker's cron internals is complicated.
        // As such, we test that our tasks are persisted correctly to the table used by
        // Graphile Worker. Unit tests ensure that we set the right tasks and that the handlers
        // are correct once the worker triggers them.
        test('scheduled tasks are set up correctly in graphile worker', async () => {
            const res = await postgres.query('SELECT * FROM graphile_worker.known_crontabs')
            expect(res.rows).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        identifier: 'runEveryHour',
                    }),
                    expect.objectContaining({
                        identifier: 'runEveryDay',
                    }),
                    expect.objectContaining({
                        identifier: 'runEveryMinute',
                    }),
                ])
            )
        })
    })
})

const capture = async (
    producer: Producer,
    teamId: number,
    distinctId: string,
    uuid: string,
    event: string,
    properties: object = {}
) => {
    await producer.send({
        topic: 'events_plugin_ingestion_test',
        messages: [
            {
                key: teamId.toString(),
                value: JSON.stringify({
                    distinct_id: distinctId,
                    ip: '',
                    site_url: '',
                    team_id: teamId,
                    now: new Date(),
                    sent_at: new Date(),
                    uuid: uuid,
                    data: JSON.stringify({
                        event,
                        properties: { ...properties, uuid },
                        distinct_id: distinctId,
                        team_id: teamId,
                        timestamp: new Date(),
                    }),
                }),
            },
        ],
    })
}

const createPlugin = async (pgClient: Pool, plugin: Omit<Plugin, 'id'>) => {
    return await insertRow(pgClient, 'posthog_plugin', {
        ...plugin,
        config_schema: {},
        from_json: false,
        from_web: false,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        is_preinstalled: false,
        capabilities: {},
    })
}

const createPluginConfig = async (
    pgClient: Pool,
    pluginConfig: Omit<PluginConfig, 'id' | 'created_at' | 'enabled' | 'order' | 'config' | 'has_error'>
) => {
    return await insertRow(pgClient, 'posthog_pluginconfig', {
        ...pluginConfig,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        enabled: true,
        order: 0,
        config: {},
    })
}

const createAndReloadPluginConfig = async (pgClient: Pool, teamId: number, pluginId: number, redis: Redis.Redis) => {
    const pluginConfig = await createPluginConfig(postgres, { team_id: teamId, plugin_id: pluginId })
    // Make sure the plugin server reloads the newly created plugin config.
    // TODO: avoid reaching into the pluginsServer internals and rather use
    // the pubsub mechanism to trigger this.
    await redis.publish('reload-plugins', '')
    return pluginConfig
}

const fetchEvents = async (clickHouseClient: ClickHouse, teamId: number) => {
    const queryResult = (await clickHouseClient.querying(
        `SELECT * FROM events WHERE team_id = ${teamId} ORDER BY timestamp ASC`
    )) as unknown as ClickHouse.ObjectQueryResult<RawClickHouseEvent>
    return queryResult.data.map(parseRawClickHouseEvent)
}

const fetchPersons = async (clickHouseClient: ClickHouse, teamId: number) => {
    const queryResult = (await clickHouseClient.querying(
        `SELECT * FROM person WHERE team_id = ${teamId} ORDER BY created_at ASC`
    )) as unknown as ClickHouse.ObjectQueryResult<RawPerson>
    return queryResult.data
}

const fetchSessionRecordingsEvents = async (clickHouseClient: ClickHouse, teamId: number) => {
    const queryResult = (await clickHouseClient.querying(
        `SELECT * FROM session_recording_events WHERE team_id = ${teamId} ORDER BY timestamp ASC`
    )) as unknown as ClickHouse.ObjectQueryResult<RawSessionRecordingEvent>
    return queryResult.data.map((event) => {
        return {
            ...event,
            snapshot_data: event.snapshot_data ? JSON.parse(event.snapshot_data) : null,
        }
    })
}

const fetchPluginLogEntries = async (clickHouseClient: ClickHouse, pluginConfigId: number) => {
    const { data: logEntries } = (await clickHouseClient.querying(`
        SELECT * FROM plugin_log_entries
        WHERE plugin_config_id = ${pluginConfigId} AND source = 'CONSOLE'
    `)) as unknown as ClickHouse.ObjectQueryResult<PluginLogEntry>
    return logEntries.map((entry) => ({ ...entry, message: JSON.parse(entry.message) }))
}

const createOrganization = async (pgClient: Pool) => {
    const organizationId = new UUIDT().toString()
    await insertRow(pgClient, 'posthog_organization', {
        id: organizationId,
        name: 'TEST ORG',
        plugins_access_level: 9,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        personalization: '{}', // DEPRECATED
        setup_section_2_completed: true, // DEPRECATED
        for_internal_metrics: false,
        available_features: [],
        domain_whitelist: [],
        is_member_join_email_enabled: false,
        slug: Math.round(Math.random() * 10000),
    })
    return organizationId
}

const createTeam = async (pgClient: Pool, organizationId: string) => {
    const team = await insertRow(pgClient, 'posthog_team', {
        organization_id: organizationId,
        app_urls: [],
        name: 'TEST PROJECT',
        event_names: [],
        event_names_with_usage: [],
        event_properties: [],
        event_properties_with_usage: [],
        event_properties_numerical: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        anonymize_ips: false,
        completed_snippet_onboarding: true,
        ingested_event: true,
        uuid: new UUIDT().toString(),
        session_recording_opt_in: true,
        plugins_opt_in: false,
        opt_out_capture: false,
        is_demo: false,
        api_token: new UUIDT().toString(),
        test_account_filters: [],
        timezone: 'UTC',
        data_attributes: ['data-attr'],
        person_display_name_properties: [],
        access_control: false,
    })
    return team.id
}
