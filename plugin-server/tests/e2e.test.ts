import Piscina from '@posthog/piscina'
import IORedis from 'ioredis'

import { ONE_HOUR } from '../src/config/constants'
import { startPluginsServer } from '../src/main/pluginsServer'
import { LogLevel, PluginsServerConfig } from '../src/types'
import { Hub } from '../src/types'
import { delay, UUIDT } from '../src/utils/utils'
import { makePiscina } from '../src/worker/piscina'
import { createPosthog, DummyPostHog } from '../src/worker/vm/extensions/posthog'
import { writeToFile } from '../src/worker/vm/extensions/test-utils'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from './helpers/clickhouse'
import { resetKafka } from './helpers/kafka'
import { pluginConfig39 } from './helpers/plugins'
import { resetTestDatabase } from './helpers/sql'

const { console: testConsole } = writeToFile

jest.mock('../src/utils/status')
jest.setTimeout(60000) // 60 sec timeout

const extraServerConfig: Partial<PluginsServerConfig> = {
    WORKER_CONCURRENCY: 2,
    LOG_LEVEL: LogLevel.Log,
    CONVERSION_BUFFER_ENABLED: false,
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

describe('E2E', () => {
    let hub: Hub
    let stopServer: () => Promise<void>
    let posthog: DummyPostHog
    let piscina: Piscina
    let redis: IORedis.Redis

    beforeAll(async () => {
        await resetKafka(extraServerConfig)
    })

    beforeEach(async () => {
        testConsole.reset()
        await resetTestDatabase(indexJs)
        await resetTestDatabaseClickhouse(extraServerConfig)
        const startResponse = await startPluginsServer(extraServerConfig, makePiscina)
        hub = startResponse.hub
        piscina = startResponse.piscina
        stopServer = startResponse.stop
        redis = await hub.redisPool.acquire()
        posthog = createPosthog(hub, pluginConfig39)
    })

    afterEach(async () => {
        await hub.redisPool.release(redis)
        await stopServer()
    })

    describe('ClickHouse ingestion', () => {
        test('event captured, processed, ingested', async () => {
            expect((await hub.db.fetchEvents()).length).toBe(0)

            const uuid = new UUIDT().toString()

            const event = {
                event: 'custom event',
                properties: { name: 'haha', uuid },
            }
            await posthog.capture(event.event, event.properties)

            await delayUntilEventIngested(() => hub.db.fetchEvents())

            await hub.kafkaProducer.flush()
            const events = await hub.db.fetchEvents()

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
        })

        test('correct $autocapture properties included in onEvent calls', async () => {
            // The plugin server does modifications to the `event.properties`
            // and as a results we remove the initial `$elements` from the
            // object. Thus we want to ensure that this information is passed
            // through to any plugins with `onEvent` handlers
            const properties = {
                $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' }],
            }
            const event = {
                event: '$autocapture',
                properties: properties,
            }
            await posthog.capture('$autocapture', properties)

            await delayUntilEventIngested(() => hub.db.fetchEvents(), 1)

            // onEvent ran
            const consoleOutput = testConsole.read()
            expect(consoleOutput).toEqual([['processEvent'], ['onEvent', expect.any(String)]])

            const onEventEvent = JSON.parse(consoleOutput[1][1])
            expect(onEventEvent.elements).toEqual([
                { attributes: {}, nth_child: 1, nth_of_type: 2, tag_name: 'div', text: '💻' },
            ])
        })

        test('snapshot captured, processed, ingested', async () => {
            expect((await hub.db.fetchSessionRecordingEvents()).length).toBe(0)

            await posthog.capture('$snapshot', { $session_id: '1234abc', $snapshot_data: 'yes way' })

            await delayUntilEventIngested(() => hub.db.fetchSessionRecordingEvents())

            await hub.kafkaProducer.flush()
            const events = await hub.db.fetchSessionRecordingEvents()

            expect(events.length).toBe(1)

            // processEvent did not modify
            expect(events[0].snapshot_data).toEqual('yes way')

            // onSnapshot ran
            expect(testConsole.read()).toEqual([['onSnapshot', '$snapshot']])
        })

        test('console logging is persistent', async () => {
            const fetchLogs = async () => {
                const logs = await hub.db.fetchPluginLogEntries()
                return logs.filter(({ type, source }) => type === 'INFO' && source !== 'SYSTEM')
            }

            await posthog.capture('custom event', { name: 'hehe', uuid: new UUIDT().toString() })
            await hub.kafkaProducer.flush()

            await delayUntilEventIngested(() => hub.db.fetchEvents())
            // :KLUDGE: Force workers to emit their logs, otherwise they might never get cpu time.
            await piscina.broadcastTask({ task: 'flushKafkaMessages' })

            const pluginLogEntries = await delayUntilEventIngested(fetchLogs)
            expect(pluginLogEntries).toContainEqual(
                expect.objectContaining({
                    type: 'INFO',
                    message: 'amogus',
                })
            )
        })
    })

    // TODO: we should enable this test again - they are enabled on self-hosted
    // historical exports are currently disabled
    describe.skip('export historical events', () => {
        const awaitHistoricalEventLogs = async () =>
            await new Promise((resolve) => {
                resolve(testConsole.read().filter((log) => log[0] === 'exported historical event'))
            })

        test('export historical events', async () => {
            await posthog.capture('historicalEvent1')
            await posthog.capture('historicalEvent2')
            await posthog.capture('historicalEvent3')
            await posthog.capture('historicalEvent4')

            await delayUntilEventIngested(() => hub.db.fetchEvents(), 4)

            // the db needs to have events _before_ running setupPlugin
            // to test payloads with missing timestamps
            // hence we reload here
            await piscina.broadcastTask({ task: 'teardownPlugins' })
            await delay(2000)

            await piscina.broadcastTask({ task: 'reloadPlugins' })
            await delay(2000)

            const historicalEvents = await hub.db.fetchEvents()
            expect(historicalEvents.length).toBe(4)

            const exportedEventsCountBeforeJob = testConsole
                .read()
                .filter((log) => log[0] === 'exported historical event').length
            expect(exportedEventsCountBeforeJob).toEqual(0)

            // TODO: trigger job via graphile here

            await delayUntilEventIngested(awaitHistoricalEventLogs as any, 4, 1000, 50)

            const exportLogs = testConsole.read().filter((log) => log[0] === 'exported historical event')
            const exportedEventsCountAfterJob = exportLogs.length
            const exportedEvents = exportLogs.map((log) => log[1])

            expect(exportedEventsCountAfterJob).toEqual(4)
            expect(exportedEvents.map((e) => e.event)).toEqual(
                expect.arrayContaining(['historicalEvent1', 'historicalEvent2', 'historicalEvent3', 'historicalEvent4'])
            )
            expect(Object.keys(exportedEvents[0].properties)).toEqual(
                expect.arrayContaining([
                    '$$historical_export_source_db',
                    '$$is_historical_export_event',
                    '$$historical_export_timestamp',
                ])
            )

            expect(exportedEvents[0].properties['$$historical_export_source_db']).toEqual('clickhouse')
        })

        test('export historical events with specified timestamp boundaries', async () => {
            await posthog.capture('historicalEvent1')
            await posthog.capture('historicalEvent2')
            await posthog.capture('historicalEvent3')
            await posthog.capture('historicalEvent4')

            await delayUntilEventIngested(() => hub.db.fetchEvents(), 4)

            const historicalEvents = await hub.db.fetchEvents()
            expect(historicalEvents.length).toBe(4)

            const exportedEventsCountBeforeJob = testConsole
                .read()
                .filter((log) => log[0] === 'exported historical event').length
            expect(exportedEventsCountBeforeJob).toEqual(0)

            // TODO: trigger job via graphile here

            await delayUntilEventIngested(awaitHistoricalEventLogs as any, 4, 1000)

            const exportLogs = testConsole.read().filter((log) => log[0] === 'exported historical event')
            const exportedEventsCountAfterJob = exportLogs.length
            const exportedEvents = exportLogs.map((log) => log[1])

            expect(exportedEventsCountAfterJob).toEqual(4)
            expect(exportedEvents.map((e) => e.event)).toEqual(
                expect.arrayContaining(['historicalEvent1', 'historicalEvent2', 'historicalEvent3', 'historicalEvent4'])
            )
            expect(Object.keys(exportedEvents[0].properties)).toEqual(
                expect.arrayContaining([
                    '$$historical_export_source_db',
                    '$$is_historical_export_event',
                    '$$historical_export_timestamp',
                ])
            )

            expect(exportedEvents[0].properties['$$historical_export_source_db']).toEqual('clickhouse')
        })

        test('correct $elements included in historical event', async () => {
            const properties = {
                $elements: [
                    { tag_name: 'a', nth_child: 1, nth_of_type: 2, attr__class: 'btn btn-sm' },
                    { tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' },
                ],
            }
            await posthog.capture('$autocapture', properties)

            await delayUntilEventIngested(() => hub.db.fetchEvents(), 1)

            const historicalEvents = await hub.db.fetchEvents()
            expect(historicalEvents.length).toBe(1)

            // TODO: trigger job via graphile here

            const exportLogs = testConsole.read().filter((log) => log[0] === 'exported historical event')
            const exportedEventsCountAfterJob = exportLogs.length
            const exportedEvents = exportLogs.map((log) => log[1])

            expect(exportedEventsCountAfterJob).toEqual(1)
            expect(exportedEvents.map((e) => e.event)).toEqual(['$autocapture'])

            expect(Object.keys(exportedEvents[0].properties)).toEqual(
                expect.arrayContaining([
                    '$$historical_export_source_db',
                    '$$is_historical_export_event',
                    '$$historical_export_timestamp',
                ])
            )

            expect(exportedEvents[0].properties['$elements']).toEqual([
                {
                    attr_class: 'btn btn-sm',
                    attributes: { attr__class: 'btn btn-sm' },
                    nth_child: 1,
                    nth_of_type: 2,
                    order: 0,
                    tag_name: 'a',
                },
                { $el_text: '💻', attributes: {}, nth_child: 1, nth_of_type: 2, order: 1, tag_name: 'div', text: '💻' },
            ])
        })
    })
})
