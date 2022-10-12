import ClickHouse from '@posthog/clickhouse'
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
    RawSessionRecordingEvent,
} from '../src/types'
import { Plugin, PluginConfig } from '../src/types'
import { parseRawClickHouseEvent } from '../src/utils/event'
import { UUIDT } from '../src/utils/utils'
import { writeToFile } from '../src/worker/vm/extensions/test-utils'
import { delayUntilEventIngested } from './helpers/clickhouse'
import { insertRow, POSTGRES_TRUNCATE_TABLES_QUERY } from './helpers/sql'

const { console: testConsole } = writeToFile

jest.setTimeout(60000) // 60 sec timeout

const extraServerConfig: Partial<PluginsServerConfig> = {
    WORKER_CONCURRENCY: 1,
    LOG_LEVEL: LogLevel.Log,
    // Conversion buffer is now default enabled, so we should enable it for
    // tests.
    CONVERSION_BUFFER_ENABLED: true,
    BUFFER_CONVERSION_SECONDS: 0,
    // Make sure producer flushes for each message immediately. Note that this
    // does mean that we are not testing the async nature of the producer by
    // doing this.
    // TODO: update producer queueMessage functionality to have flush run async
    // even if the queue is full and flush needs to be called.
    KAFKA_MAX_MESSAGE_BATCH_SIZE: 0,
}

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

    export function onSnapshot (event) {
        testConsole.log('onSnapshot', event.event)
    }


    export async function exportEvents(events) {
        for (const event of events) {
            if (event.properties && event.properties['$$is_historical_export_event']) {
                testConsole.log('exported historical event', event)
            }
        }
    }

    export async function runEveryMinute() {}
`

const startMultiServer = async () => {
    const ingestionServer = startPluginsServer({ extraServerConfig, PLUGIN_SERVER_MODE: 'ingestion' })
    const asyncServer = startPluginsServer({ extraServerConfig, PLUGIN_SERVER_MODE: 'async' })
    return await Promise.all([ingestionServer, asyncServer])
}

const startSingleServer = async () => {
    return [await startPluginsServer(extraServerConfig)]
}

describe.each([[startSingleServer], [startMultiServer]])('E2E', (pluginServer) => {
    let pluginsServers: ServerInstance[]
    let producer: Producer
    let clickHouseClient: ClickHouse
    let postgres: Pool
    let kafka: Kafka
    let organizationId: string
    let teamId: number
    let plugin: Plugin
    let pluginConfig: PluginConfig

    beforeAll(async () => {
        postgres = new Pool({ connectionString: defaultConfig.DATABASE_URL! })
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

        organizationId = await createOrganization(postgres)
        plugin = await createPlugin(postgres, {
            organization_id: organizationId,
            name: 'test plugin',
            plugin_type: 'source',
            is_global: false,
            source__index_ts: indexJs,
        })

        pluginsServers = await pluginServer()
    })

    beforeEach(async () => {
        testConsole.reset()
        teamId = await createTeam(postgres, organizationId)
        pluginConfig = await createPluginConfig(postgres, { team_id: teamId, plugin_id: plugin.id })
        // Make sure the plugin server reloads the newly created plugin config.
        // TODO: avoid reaching into the pluginsServer internals and rather use
        // the pubsub mechanism to trigger this.
        await Promise.all(pluginsServers.map((instance) => instance.piscina.broadcastTask({ task: 'reloadPlugins' })))
    })

    afterAll(async () => {
        await Promise.all(pluginsServers.map((instance) => instance.stop()))
        await producer.disconnect()
        await postgres.end()
    })

    describe(`ClickHouse ingestion (${pluginServer.name})`, () => {
        test('event captured, processed, ingested', async () => {
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
        }, 5000)

        test('correct $autocapture properties included in onEvent calls', async () => {
            // The plugin server does modifications to the `event.properties`
            // and as a results we remove the initial `$elements` from the
            // object. Thus we want to ensure that this information is passed
            // through to any plugins with `onEvent` handlers
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
                { attributes: {}, nth_child: 1, nth_of_type: 2, tag_name: 'div', text: '💻' },
            ])
        }, 5000)

        test('snapshot captured, processed, ingested', async () => {
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
        }, 5000)

        test('console logging is persistent', async () => {
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
        }, 5000)
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

const fetchEvents = async (clickHouseClient: ClickHouse, teamId: number) => {
    const queryResult = (await clickHouseClient.querying(
        `SELECT * FROM events WHERE team_id = ${teamId} ORDER BY timestamp ASC`
    )) as unknown as ClickHouse.ObjectQueryResult<RawClickHouseEvent>
    return queryResult.data.map(parseRawClickHouseEvent)
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
