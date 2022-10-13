import ClickHouse from '@posthog/clickhouse'
import { Kafka, Partitioners, Producer } from 'kafkajs'
import { Pool } from 'pg'

import { defaultConfig } from '../src/config/config'
import { ONE_HOUR, ONE_MINUTE } from '../src/config/constants'
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
import { writeToFile } from '../src/worker/vm/extensions/test-utils'
import { delayUntilEventIngested } from '../tests/helpers/clickhouse'
import { insertRow } from '../tests/helpers/sql'

const { console: testConsole } = writeToFile

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

    organizationId = await createOrganization(postgres)
})

beforeEach(() => jest.useRealTimers())

afterAll(async () => {
    await Promise.all([producer.disconnect(), postgres.end()])
})

describe.each([[startSingleServer], [startMultiServer]])('E2E', (pluginServer) => {
    let pluginsServers: ServerInstance[]

    beforeAll(async () => {
        pluginsServers = await pluginServer()
    })

    beforeEach(() => {
        testConsole.reset()
    })

    afterAll(async () => {
        await Promise.all(pluginsServers.map((instance) => instance.stop()))
    })

    describe(`plugin method tests (${pluginServer.name})`, () => {
        let plugin: Plugin

        const indexJs = `
            import { console as testConsole } from 'test-utils/write-to-file'
    
            export async function processEvent (event) {
                testConsole.log('processEvent')
                console.info('amogus')
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
                testConsole.log('onEvent', JSON.stringify(event))
            }
    
            export async function exportEvents(events) {
                for (const event of events) {
                    if (event.properties && event.properties['$$is_historical_export_event']) {
                        testConsole.log('exported historical event', event)
                    }
                }
            }

            export async function runEveryMinute() {
                testConsole.log('runEveryMinute')
            }
        `

        beforeAll(async () => {
            plugin = await createPlugin(postgres, {
                organization_id: organizationId,
                name: 'test plugin',
                plugin_type: 'source',
                is_global: false,
                source__index_ts: indexJs,
            })
        })

        test('event captured, processed, ingested', async () => {
            const teamId = await createTeam(postgres, organizationId)
            await createAndReloadPluginConfig(postgres, teamId, plugin.id, pluginsServers)
            const distinctId = new UUIDT().toString()
            const uuid = new UUIDT().toString()

            const event = {
                event: 'custom event',
                properties: { name: 'haha' },
            }

            await capture(producer, teamId, distinctId, uuid, event.event, event.properties)

            await delayUntilEventIngested(() => fetchEvents(clickHouseClient, teamId), 1)
            const events = await fetchEvents(clickHouseClient, teamId)
            expect(events.length).toBe(1)

            // processEvent ran and modified
            expect(events[0].properties.processed).toEqual('hell yes')
            expect(events[0].properties.upperUuid).toEqual(uuid.toUpperCase())

            // onEvent ran
            const consoleOutput = testConsole.read()
            expect(consoleOutput).toEqual([['processEvent'], ['onEvent', expect.any(String)]])

            const onEventEvent = JSON.parse(consoleOutput[1][1])
            expect(onEventEvent.event).toEqual('custom event')
            expect(onEventEvent.properties).toEqual(expect.objectContaining(event.properties))
        }, 10000)

        test('correct $autocapture properties included in onEvent calls', async () => {
            // The plugin server does modifications to the `event.properties`
            // and as a results we remove the initial `$elements` from the
            // object. Thus we want to ensure that this information is passed
            // through to any plugins with `onEvent` handlers
            const teamId = await createTeam(postgres, organizationId)
            await createAndReloadPluginConfig(postgres, teamId, plugin.id, pluginsServers)

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
            await delayUntilEventIngested(() => fetchEvents(clickHouseClient, teamId), 1)

            // onEvent ran
            const consoleOutput = testConsole.read()
            expect(consoleOutput).toEqual([['processEvent'], ['onEvent', expect.any(String)]])

            const onEventEvent = JSON.parse(consoleOutput[1][1])
            expect(onEventEvent.elements).toEqual([
                expect.objectContaining({ attributes: {}, nth_child: 1, nth_of_type: 2, tag_name: 'div', text: '💻' }),
            ])
        }, 10000)

        test('console logging is persistent', async () => {
            const teamId = await createTeam(postgres, organizationId)
            const pluginConfig = await createAndReloadPluginConfig(postgres, teamId, plugin.id, pluginsServers)

            const distinctId = new UUIDT().toString()
            const uuid = new UUIDT().toString()

            const fetchLogs = async () => {
                const logs = await fetchPluginLogEntries(clickHouseClient, pluginConfig.id)
                return logs.filter(({ type, source }) => type === 'INFO' && source !== 'SYSTEM')
            }

            await capture(producer, teamId, distinctId, uuid, 'custom event', {
                name: 'hehe',
                uuid: new UUIDT().toString(),
            })

            await delayUntilEventIngested(() => fetchEvents(clickHouseClient, teamId))

            const pluginLogEntries = await delayUntilEventIngested(fetchLogs)
            expect(pluginLogEntries).toContainEqual(
                expect.objectContaining({
                    type: 'INFO',
                    message: 'amogus',
                })
            )
        }, 10000)

        test('runEveryMinute is executed', async () => {
            // NOTE: we do not check Hour and Day, merely because if we advance
            // too much it seems we end up performing alot of reloads of
            // actions, which prevents the test from completing.
            //
            // Note this also somewhat plays havoc with the Kafka consumer
            // sessions.
            jest.useFakeTimers({ advanceTimers: 30 })

            const teamId = await createTeam(postgres, organizationId)
            await createAndReloadPluginConfig(postgres, teamId, plugin.id, pluginsServers)

            await delayUntilEventIngested(() => fetchEvents(clickHouseClient, teamId))

            jest.advanceTimersByTime(ONE_MINUTE)
            await delayUntilEventIngested(() => testConsole.read().filter((line) => line[0] === 'runEveryMinute'))
            const consoleOutput = testConsole.read()
            expect(consoleOutput.flatMap((x) => x)).toContain('runEveryMinute')
        })
    })

    describe(`session recording ingestion (${pluginServer.name})`, () => {
        test('snapshot captured, processed, ingested', async () => {
            const teamId = await createTeam(postgres, organizationId)
            const distinctId = new UUIDT().toString()
            const uuid = new UUIDT().toString()

            await capture(producer, teamId, distinctId, uuid, '$snapshot', {
                $session_id: '1234abc',
                $snapshot_data: 'yes way',
            })

            await delayUntilEventIngested(() => fetchSessionRecordingsEvents(clickHouseClient, teamId), 1)
            const events = await fetchSessionRecordingsEvents(clickHouseClient, teamId)
            expect(events.length).toBe(1)

            // processEvent did not modify
            expect(events[0].snapshot_data).toEqual('yes way')
        }, 10000)
    })

    describe(`event ingestion (${pluginServer.name})`, () => {
        test('anonymous event recieves same person_id if $identify happenes shortly after', async () => {
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

            await delayUntilEventIngested(() => fetchEvents(clickHouseClient, teamId), 3)
            const events = await fetchEvents(clickHouseClient, teamId)
            expect(new Set(events.map((event) => event.person_id)).size).toBe(1)

            await delayUntilEventIngested(() => fetchPersons(clickHouseClient, teamId), 1)
            const persons = await fetchPersons(clickHouseClient, teamId)
            expect(persons.length).toBe(1)
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

const createAndReloadPluginConfig = async (
    pgClient: Pool,
    teamId: number,
    pluginId: number,
    pluginsServers: ServerInstance[]
) => {
    const pluginConfig = await createPluginConfig(postgres, { team_id: teamId, plugin_id: pluginId })
    // Make sure the plugin server reloads the newly created plugin config.
    // TODO: avoid reaching into the pluginsServer internals and rather use
    // the pubsub mechanism to trigger this.
    await Promise.all(pluginsServers.map((instance) => instance.piscina.broadcastTask({ task: 'reloadPlugins' })))
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
        WHERE plugin_config_id = ${pluginConfigId}
    `)) as unknown as ClickHouse.ObjectQueryResult<PluginLogEntry>
    return logEntries
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
