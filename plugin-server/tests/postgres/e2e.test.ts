import * as IORedis from 'ioredis'

import { startPluginsServer } from '../../src/main/pluginsServer'
import { LogLevel } from '../../src/types'
import { Hub } from '../../src/types'
import { Client } from '../../src/utils/celery/client'
import { delay, UUIDT } from '../../src/utils/utils'
import { makePiscina } from '../../src/worker/piscina'
import { createPosthog, DummyPostHog } from '../../src/worker/vm/extensions/posthog'
import { writeToFile } from '../../src/worker/vm/extensions/test-utils'
import { pluginConfig39 } from '../helpers/plugins'
import { resetTestDatabase } from '../helpers/sql'
import { delayUntilEventIngested } from '../shared/process-event'

const { console: testConsole } = writeToFile
const HISTORICAL_EVENTS_COUNTER_CACHE_KEY = '@plugin/60/2/historical_events_seen'
const ONE_HOUR = 1000 * 60 * 60

jest.mock('../../src/utils/status')
jest.setTimeout(60000) // 60 sec timeout

const indexJs = `
    import { console as testConsole } from 'test-utils/write-to-file'

    export async function processEvent (event) {
        testConsole.log('processEvent')
        console.info('amogus')
        event.properties.processed = 'hell yes'
        event.properties.upperUuid = event.properties.uuid?.toUpperCase()
        event.properties['$snapshot_data'] = 'no way'
        const counter = await meta.cache.get('events_seen')
        return event
    }

    export function onEvent (event, { global }) {
        // we use this to mock setupPlugin being 
        // run after some events were already ingested
        global.timestampBoundariesForTeam = {
            max: new Date(),
            min: new Date(Date.now()-${ONE_HOUR})
        }
        testConsole.log('onEvent', event.event)
    }

    export function onSnapshot (event) {
        testConsole.log('onSnapshot', event.event)
    }

    export async function exportEvents(events) {
        for (const event of events) {
            testConsole.log('exported event', event.event)
        }
    }
`

// TODO: merge these tests with clickhouse/e2e.test.ts
describe('e2e', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let posthog: DummyPostHog
    let redis: IORedis.Redis

    beforeEach(async () => {
        testConsole.reset()
        console.debug = jest.fn()

        await resetTestDatabase(indexJs)
        const startResponse = await startPluginsServer(
            {
                WORKER_CONCURRENCY: 2,
                PLUGINS_CELERY_QUEUE: 'test-plugins-celery-queue',
                CELERY_DEFAULT_QUEUE: 'test-celery-default-queue',
                LOG_LEVEL: LogLevel.Log,
                KAFKA_ENABLED: false,
            },
            makePiscina
        )
        hub = startResponse.hub
        closeHub = startResponse.stop
        redis = await hub.redisPool.acquire()

        await redis.del(hub.PLUGINS_CELERY_QUEUE)
        await redis.del(hub.CELERY_DEFAULT_QUEUE)
        await redis.del(HISTORICAL_EVENTS_COUNTER_CACHE_KEY)

        posthog = createPosthog(hub, pluginConfig39)
    })

    afterEach(async () => {
        await hub.redisPool.release(redis)
        await closeHub()
    })

    describe('e2e postgres ingestion', () => {
        test('event captured, processed, ingested', async () => {
            expect((await hub.db.fetchEvents()).length).toBe(0)

            const uuid = new UUIDT().toString()

            await posthog.capture('custom event', { name: 'haha', uuid })

            await delayUntilEventIngested(() => hub.db.fetchEvents())

            const events = await hub.db.fetchEvents()
            await delay(1000)

            expect(events.length).toBe(1)

            // processEvent ran and modified
            expect(events[0].properties.processed).toEqual('hell yes')
            expect(events[0].properties.upperUuid).toEqual(uuid.toUpperCase())

            // onEvent ran
            expect(testConsole.read()).toEqual([['processEvent'], ['onEvent', 'custom event']])
        })

        test('snapshot captured, processed, ingested', async () => {
            expect((await hub.db.fetchSessionRecordingEvents()).length).toBe(0)

            await posthog.capture('$snapshot', { $session_id: '1234abc', $snapshot_data: 'yes way' })

            await delayUntilEventIngested(() => hub.db.fetchSessionRecordingEvents())

            const events = await hub.db.fetchSessionRecordingEvents()
            await delay(1000)

            expect(events.length).toBe(1)

            // processEvent did not modify
            expect(events[0].snapshot_data).toEqual('yes way')

            // onSnapshot ran
            expect(testConsole.read()).toEqual([['onSnapshot', '$snapshot']])
        })

        test('console logging is persistent', async () => {
            const logCount = (await hub.db.fetchPluginLogEntries()).length
            const getLogsSinceStart = async () => (await hub.db.fetchPluginLogEntries()).slice(logCount)

            await posthog.capture('custom event', { name: 'hehe', uuid: new UUIDT().toString() })

            await delayUntilEventIngested(async () =>
                (await getLogsSinceStart()).filter(({ message }) => message.includes('amogus'))
            )
            const pluginLogEntries = await getLogsSinceStart()
            expect(
                pluginLogEntries.filter(({ message, type }) => message.includes('amogus') && type === 'INFO').length
            ).toEqual(1)
        })

        test('action matches are saved', async () => {
            await posthog.capture('xyz', { foo: 'bar' })

            await delayUntilEventIngested(() => hub.db.fetchActionMatches())

            const savedMatches = await hub.db.fetchActionMatches()

            expect(savedMatches).toStrictEqual([
                { id: expect.any(Number), event_id: expect.any(Number), action_id: 69 },
            ])
        })
    })

    describe('e2e export historical events', () => {
        const awaitLogs = async () =>
            await new Promise((resolve) => {
                resolve(testConsole.read().filter((log) => log[0] === 'exported event'))
            })

        test('export historical events', async () => {
            await posthog.capture('historicalEvent1')
            await posthog.capture('historicalEvent2')
            await posthog.capture('historicalEvent3')
            await posthog.capture('historicalEvent4')

            await delayUntilEventIngested(() => hub.db.fetchEvents(), 4)
            await delay(100)

            const historicalEvents = await hub.db.fetchEvents()
            expect(historicalEvents.length).toBe(4)

            const exportedEventsCountBeforeJob = testConsole.read().filter((log) => log[0] === 'exported event').length
            expect(exportedEventsCountBeforeJob).toEqual(0)

            const kwargs = {
                pluginConfigTeam: 2,
                pluginConfigId: 39,
                type: 'Export historical events',
                jobOp: 'start',
                payload: {},
            }
            const args = Object.values(kwargs)

            const client = new Client(hub.db, hub.PLUGINS_CELERY_QUEUE)
            client.sendTask('posthog.tasks.plugins.plugin_job', args, {})

            await delayUntilEventIngested(awaitLogs, 4)
            await delay(100)

            const exportedEventsAfterJob = testConsole.read().filter((log) => log[0] === 'exported event')
            expect(exportedEventsAfterJob.length).toEqual(4)
            expect(exportedEventsAfterJob.map((log) => log[1])).toEqual(
                expect.arrayContaining(['historicalEvent1', 'historicalEvent2', 'historicalEvent3', 'historicalEvent4'])
            )
        })

        test('export historical events with specified timestamp boundaries', async () => {
            await posthog.capture('historicalEvent1')
            await posthog.capture('historicalEvent2')
            await posthog.capture('historicalEvent3')
            await posthog.capture('historicalEvent4')

            await delayUntilEventIngested(() => hub.db.fetchEvents(), 4)
            await delay(1000)

            const historicalEvents = await hub.db.fetchEvents()
            expect(historicalEvents.length).toBe(4)

            const exportedEventsCountBeforeJob = testConsole.read().filter((log) => log[0] === 'exported event').length
            expect(exportedEventsCountBeforeJob).toEqual(0)

            const kwargs = {
                pluginConfigTeam: 2,
                pluginConfigId: 39,
                type: 'Export historical events',
                jobOp: 'start',
                payload: {
                    dateFrom: new Date().toISOString(),
                    dateTo: new Date().toISOString(),
                },
            }
            let args = Object.values(kwargs)

            const client = new Client(hub.db, hub.PLUGINS_CELERY_QUEUE)
            client.sendTask('posthog.tasks.plugins.plugin_job', args, {})

            await delay(10000)

            const exportedEventsCountAfterFirstJob = testConsole
                .read()
                .filter((log) => log[0] === 'exported event').length
            expect(exportedEventsCountAfterFirstJob).toEqual(0)

            kwargs.payload.dateFrom = new Date(Date.now() - ONE_HOUR).toISOString()
            args = Object.values(kwargs)
            client.sendTask('posthog.tasks.plugins.plugin_job', args, {})

            await delayUntilEventIngested(awaitLogs, 4)
            await delay(1000)

            const exportedEventsAfterSecondJob = testConsole.read().filter((log) => log[0] === 'exported event')
            expect(exportedEventsAfterSecondJob.length).toEqual(4)
            expect(exportedEventsAfterSecondJob.map((log) => log[1])).toEqual(
                expect.arrayContaining(['historicalEvent1', 'historicalEvent2', 'historicalEvent3', 'historicalEvent4'])
            )
        })
    })
})
