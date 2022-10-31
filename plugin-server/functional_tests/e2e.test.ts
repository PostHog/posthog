import ClickHouse from '@posthog/clickhouse'
import { createServer, Server } from 'http'
import Redis from 'ioredis'
import { Consumer, Kafka, KafkaMessage, Partitioners, Producer } from 'kafkajs'
import { Pool } from 'pg'
import { v4 as uuidv4 } from 'uuid'

import { defaultConfig } from '../src/config/config'
import { ONE_HOUR } from '../src/config/constants'
import {
    KAFKA_BUFFER,
    KAFKA_EVENTS_DEAD_LETTER_QUEUE,
    KAFKA_EVENTS_JSON,
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_GROUPS,
    KAFKA_PERSON,
    KAFKA_PERSON_DISTINCT_ID,
    KAFKA_PERSON_UNIQUE_ID,
    KAFKA_PLUGIN_LOG_ENTRIES,
    KAFKA_SESSION_RECORDING_EVENTS,
} from '../src/config/kafka-topics'
import { ServerInstance, startPluginsServer } from '../src/main/pluginsServer'
import {
    ActionStep,
    LogLevel,
    PluginLogEntry,
    PluginsServerConfig,
    RawAction,
    RawClickHouseEvent,
    RawPerson,
    RawSessionRecordingEvent,
} from '../src/types'
import { Plugin, PluginConfig } from '../src/types'
import { parseRawClickHouseEvent } from '../src/utils/event'
import { UUIDT } from '../src/utils/utils'
import { delayUntilEventIngested } from '../tests/helpers/clickhouse'
import { createTopics } from '../tests/helpers/kafka'
import { insertRow } from '../tests/helpers/sql'

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
    const asyncServer = startPluginsServer({ ...extraServerConfig, PLUGIN_SERVER_MODE: 'exports' })
    const jobsServer = startPluginsServer({ ...extraServerConfig, PLUGIN_SERVER_MODE: 'jobs' })
    const schedulerServer = startPluginsServer({ ...extraServerConfig, PLUGIN_SERVER_MODE: 'scheduler' })

    return await Promise.all([ingestionServer, asyncServer, jobsServer, schedulerServer])
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
    await createTopics(kafka, [
        KAFKA_EVENTS_JSON,
        KAFKA_EVENTS_PLUGIN_INGESTION,
        KAFKA_BUFFER,
        KAFKA_GROUPS,
        KAFKA_SESSION_RECORDING_EVENTS,
        KAFKA_PERSON,
        KAFKA_PERSON_UNIQUE_ID,
        KAFKA_PERSON_DISTINCT_ID,
        KAFKA_PLUGIN_LOG_ENTRIES,
        KAFKA_EVENTS_DEAD_LETTER_QUEUE,
    ])
    producer = kafka.producer({ createPartitioner: Partitioners.DefaultPartitioner })
    await producer.connect()
    redis = new Redis(defaultConfig.REDIS_URL)

    organizationId = await createOrganization(postgres)
})

afterAll(async () => {
    await Promise.all([producer.disconnect(), postgres.end(), redis.disconnect()])
})

describe.each([[startSingleServer], [startMultiServer]])('E2E', (pluginServer) => {
    let pluginsServers: ServerInstance[]

    beforeAll(async () => {
        pluginsServers = await pluginServer()
    })

    afterAll(async () => {
        await Promise.all(pluginsServers.map((instance) => instance.stop()))
    })

    describe(`plugin method tests (${pluginServer.name})`, () => {
        const indexJs = `
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
        `

        test('event captured, processed, ingested', async () => {
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
        })

        test('correct $autocapture properties included in onEvent calls', async () => {
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
        }, 20000)
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

            await delayUntilEventIngested(() => fetchSessionRecordingsEvents(clickHouseClient, teamId), 1, 500, 40)
            const events = await fetchSessionRecordingsEvents(clickHouseClient, teamId)
            expect(events.length).toBe(1)

            // processEvent did not modify
            expect(events[0].snapshot_data).toEqual('yes way')
        }, 20000)
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

            const events = await delayUntilEventIngested(() => fetchEvents(clickHouseClient, teamId), 3, 500, 40)
            expect(events.length).toBe(3)
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

        test('exporting events on ingestion', async () => {
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

            const events = await delayUntilEventIngested(() => fetchEvents(clickHouseClient, teamId), 1, 500, 40)
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

        test('exporting $autocapture events on ingestion', async () => {
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
            await capture(producer, teamId, distinctId, uuid, '$autocapture', {
                name: 'hehe',
                uuid: new UUIDT().toString(),
                $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' }],
            })

            const events = await delayUntilEventIngested(() => fetchEvents(clickHouseClient, teamId), 1, 500, 40)
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
        })

        test('historical exports', async () => {
            const teamId = await createTeam(postgres, organizationId)
            const distinctId = new UUIDT().toString()
            const uuid = new UUIDT().toString()

            const plugin = await createPlugin(postgres, {
                organization_id: organizationId,
                name: 'export plugin',
                plugin_type: 'source',
                is_global: false,
                source__index_ts: indexJs,
            })
            const pluginConfig = await createAndReloadPluginConfig(postgres, teamId, plugin.id, redis)

            // First let's capture an event and wait for it to be ingested so
            // so we can check that the historical event is the same as the one
            // passed to processEvent on initial ingestion.
            await capture(producer, teamId, distinctId, uuid, '$autocapture', {
                name: 'hehe',
                uuid: new UUIDT().toString(),
                $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' }],
            })

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
            const [exportedEvent] = exportEvents[0].message[1]

            // NOTE: the frontend doesn't actually push to this queue but rather
            // adds directly to PostgreSQL using the graphile-worker stored
            // procedure `add_job`. I'd rather keep these tests graphile
            // unaware.
            await producer.send({
                topic: 'jobs_test',
                messages: [
                    {
                        key: teamId.toString(),
                        value: JSON.stringify({
                            type: 'Export historical events',
                            pluginConfigId: pluginConfig.id,
                            pluginConfigTeam: teamId,
                            payload: {
                                dateFrom: new Date(Date.now() - 60000).toISOString(),
                                dateTo: new Date(Date.now()).toISOString(),
                            },
                        }),
                    },
                ],
            })

            // Then check that the exportEvents function was called with the
            // same data that was used with the non-historical export, with the
            // additions of details related to the historical export.
            const historicallyExportedEvents = await delayUntilEventIngested(
                async () =>
                    (await fetchPluginLogEntries(clickHouseClient, pluginConfig.id))
                        .filter(({ message: [method] }) => method === 'exportEvents')
                        .filter(({ message: [, events] }) =>
                            events.some((event) => event.properties['$$is_historical_export_event'])
                        ),
                1,
                500,
                40
            )

            expect(historicallyExportedEvents.length).toBeGreaterThan(0)

            const historicallyExportedEvent = historicallyExportedEvents[0].message[1]
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
        })

        test('historical exports v2', async () => {
            const teamId = await createTeam(postgres, organizationId)
            const distinctId = new UUIDT().toString()
            const uuid = new UUIDT().toString()

            const plugin = await createPlugin(postgres, {
                organization_id: organizationId,
                name: 'export plugin',
                plugin_type: 'source',
                is_global: false,
                source__index_ts: indexJs,
            })
            const pluginConfig = await createAndReloadPluginConfig(postgres, teamId, plugin.id, redis)

            // First let's capture an event and wait for it to be ingested so
            // so we can check that the historical event is the same as the one
            // passed to processEvent on initial ingestion.
            await capture(producer, teamId, distinctId, uuid, '$autocapture', {
                name: 'hehe',
                uuid: new UUIDT().toString(),
                $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' }],
            })

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
            const [exportedEvent] = exportEvents[0].message[1]

            // NOTE: the frontend doesn't actually push to this queue but rather
            // adds directly to PostgreSQL using the graphile-worker stored
            // procedure `add_job`. I'd rather keep these tests graphile
            // unaware.
            await producer.send({
                topic: 'jobs_test',
                messages: [
                    {
                        key: teamId.toString(),
                        value: JSON.stringify({
                            type: 'Export historical events V2',
                            pluginConfigId: pluginConfig.id,
                            pluginConfigTeam: teamId,
                            payload: {
                                dateRange: [
                                    new Date(Date.now() - 60000).toISOString(),
                                    new Date(Date.now()).toISOString(),
                                ],
                                $job_id: 'test',
                                parallelism: 1,
                            },
                        }),
                    },
                ],
            })

            // Then check that the exportEvents function was called with the
            // same data that was used with the non-historical export, with the
            // additions of details related to the historical export.
            const historicallyExportedEvents = await delayUntilEventIngested(
                async () =>
                    (await fetchPluginLogEntries(clickHouseClient, pluginConfig.id))
                        .filter(({ message: [method] }) => method === 'exportEvents')
                        .filter(({ message: [, events] }) =>
                            events.some((event) => event.properties['$$is_historical_export_event'])
                        ),
                1,
                500,
                40
            )

            expect(historicallyExportedEvents.length).toBeGreaterThan(0)

            const historicallyExportedEvent = historicallyExportedEvents[0].message[1]
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
        })
    })

    describe(`plugin jobs (${pluginServer.name})`, () => {
        test('can call runNow from onEvent', async () => {
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

        test('can call runNow from processEvent', async () => {
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

        test('runEveryMinute is executed', async () => {
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
        }, 120000)
    })

    describe(`webhooks (${pluginServer.name})`, () => {
        let server: Server
        let webHookCalledWith: any

        beforeAll(() => {
            server = createServer((req, res) => {
                let body = ''
                req.on('data', (chunk) => {
                    body += chunk
                })
                req.on('end', () => {
                    webHookCalledWith = JSON.parse(body)
                    res.writeHead(200, { 'Content-Type': 'text/plain' })
                    res.end()
                })
            })
            server.listen()
        })

        beforeEach(() => {
            webHookCalledWith = undefined
        })

        afterAll(() => {
            server.close()
        })

        test('fires slack webhook', async () => {
            // Create an action with post_to_slack enabled.
            // NOTE: I'm not 100% sure how this works i.e. what all the step
            // configuration means so there's probably a more succinct way to do
            // this.
            const distinctId = new UUIDT().toString()

            const teamId = await createTeam(postgres, organizationId, `http://localhost:${server.address()?.port}`)
            const user = await createUser(postgres, teamId, new UUIDT().toString())
            await createAction(
                postgres,
                {
                    team_id: teamId,
                    name: 'slack',
                    description: 'slack',
                    created_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                    deleted: false,
                    post_to_slack: true,
                    slack_message_format: 'default',
                    created_by_id: user.id,
                    is_calculating: false,
                    last_calculated_at: new Date().toISOString(),
                },
                [
                    {
                        name: 'slack',
                        tag_name: 'div',
                        text: 'text',
                        href: null,
                        url: 'http://localhost:8000',
                        url_matching: null,
                        event: '$autocapture',
                        properties: null,
                        selector: null,
                    },
                ]
            )

            await reloadActions(redis)

            await capture(producer, teamId, distinctId, new UUIDT().toString(), '$autocapture', {
                name: 'hehe',
                uuid: new UUIDT().toString(),
                $current_url: 'http://localhost:8000',
                $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: 'text' }],
            })

            for (const attempt in Array.from(Array(10).keys())) {
                console.debug(`Attempt ${attempt} to check webhook was called`)
                if (webHookCalledWith) {
                    break
                }
                await new Promise((resolve) => setTimeout(resolve, 1000))
            }

            expect(webHookCalledWith).toEqual({ text: 'default' })
        })
    })

    describe(`jobs-consumer (${pluginServer.name})`, () => {
        // Test out some error cases that we wouldn't be able to handle without
        // producing to the jobs queue directly.

        let dlq: KafkaMessage[]
        let dlqConsumer: Consumer

        beforeAll(async () => {
            dlq = []
            dlqConsumer = kafka.consumer({ groupId: 'jobs-consumer-test' })
            await dlqConsumer.subscribe({ topic: 'jobs_dlq_test' })
            await dlqConsumer.run({
                eachMessage: ({ message }) => {
                    dlq.push(message)
                    return Promise.resolve()
                },
            })
        })

        afterAll(async () => {
            await dlqConsumer.disconnect()
        })

        test('handles empty messages', async () => {
            const key = uuidv4()

            await producer.send({
                topic: 'jobs_test',
                messages: [
                    {
                        key: key,
                        value: null,
                    },
                ],
            })

            const messages = await delayUntilEventIngested(() =>
                dlq.filter((message) => message.key?.toString() === key)
            )
            expect(messages.length).toBe(1)
        })

        test('handles invalid JSON', async () => {
            const key = uuidv4()

            await producer.send({
                topic: 'jobs_test',
                messages: [
                    {
                        key: key,
                        value: 'invalid json',
                    },
                ],
            })

            const messages = await delayUntilEventIngested(() =>
                dlq.filter((message) => message.key?.toString() === key)
            )
            expect(messages.length).toBe(1)
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

const reloadActions = async (redis: Redis.Redis) => {
    await redis.publish('reload-actions', '')
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
        slug: Math.round(Math.random() * 20000),
    })
    return organizationId
}

const createTeam = async (pgClient: Pool, organizationId: string, slack_incoming_webhook?: string) => {
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
        slack_incoming_webhook,
    })
    return team.id
}

const createAction = async (
    pgClient: Pool,
    action: Omit<RawAction, 'id'>,
    steps: Omit<ActionStep, 'id' | 'action_id'>[]
) => {
    const actionRow = await insertRow(pgClient, 'posthog_action', action)
    for (const step of steps) {
        await insertRow(pgClient, 'posthog_actionstep', {
            ...step,
            action_id: actionRow.id,
        })
    }
    return action
}

const createUser = async (pgClient: Pool, teamId: number, email: string) => {
    return await insertRow(pgClient, 'posthog_user', {
        password: 'abc',
        email,
        first_name: '',
        last_name: '',
        email_opt_in: false,
        distinct_id: email,
        is_staff: false,
        is_active: true,
        date_joined: new Date().toISOString(),
        events_column_config: '{}',
        uuid: new UUIDT().toString(),
    })
}
