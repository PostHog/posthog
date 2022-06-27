import IORedis from 'ioredis'
import { DateTime } from 'luxon'

import { ONE_HOUR } from '../src/config/constants'
import { KAFKA_BUFFER } from '../src/config/kafka-topics'
import { startPluginsServer } from '../src/main/pluginsServer'
import { LogLevel, PluginsServerConfig } from '../src/types'
import { Hub } from '../src/types'
import { delay, UUIDT } from '../src/utils/utils'
import { makePiscina } from '../src/worker/piscina'
import { createPosthog, DummyPostHog } from '../src/worker/vm/extensions/posthog'
import { writeToFile } from '../src/worker/vm/extensions/test-utils'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from './helpers/clickhouse'
import { spyOnKafka } from './helpers/kafka'
import { pluginConfig39 } from './helpers/plugins'
import { resetTestDatabase } from './helpers/sql'

const { console: testConsole } = writeToFile

jest.mock('../src/utils/status')
jest.setTimeout(60000) // 60 sec timeout

const extraServerConfig: Partial<PluginsServerConfig> = {
    WORKER_CONCURRENCY: 2,
    LOG_LEVEL: LogLevel.Log,
    KAFKA_PRODUCER_MAX_QUEUE_SIZE: 100, // The default in tests is 0 but here we specifically want to test batching
    KAFKA_FLUSH_FREQUENCY_MS: 5000, // Same as above, but with time
    BUFFER_CONVERSION_SECONDS: 3, // We want to test the delay mechanism, but with a much lower delay than in prod
    CONVERSION_BUFFER_ENABLED: true,
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
    testConsole.log('onEvent', event.event)
}`

describe('E2E with buffer enabled', () => {
    const delayUntilBufferMessageProduced = spyOnKafka(KAFKA_BUFFER, extraServerConfig)

    let hub: Hub
    let stopServer: () => Promise<void>
    let posthog: DummyPostHog
    let redis: IORedis.Redis

    beforeEach(async () => {
        testConsole.reset()
        await resetTestDatabase(indexJs)
        await resetTestDatabaseClickhouse(extraServerConfig)
        const startResponse = await startPluginsServer(extraServerConfig, makePiscina)
        hub = startResponse.hub
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

            await posthog.capture('custom event via buffer', { name: 'hehe', uuid })
            await hub.kafkaProducer.flush()

            const bufferTopicMessages = await delayUntilBufferMessageProduced()
            await delayUntilEventIngested(() => hub.db.fetchEvents(), undefined, undefined, 200)
            const events = await hub.db.fetchEvents()

            expect(bufferTopicMessages.filter((message) => message.properties.uuid === uuid).length).toBe(1)
            expect(events.length).toBe(1)

            // processEvent ran and modified
            expect(events[0].properties.processed).toEqual('hell yes')
            expect(events[0].properties.upperUuid).toEqual(uuid.toUpperCase())

            // onEvent ran
            expect(testConsole.read()).toEqual([['processEvent'], ['onEvent', 'custom event via buffer']])
        })

        test('three events captured, processed, ingested', async () => {
            expect((await hub.db.fetchEvents()).length).toBe(0)

            const uuid1 = new UUIDT().toString()
            const uuid2 = new UUIDT().toString()
            const uuid3 = new UUIDT().toString()

            // Batch 1
            await posthog.capture('custom event via buffer', { name: 'hehe', uuid: uuid1 })
            await posthog.capture('custom event via buffer', { name: 'hoho', uuid: uuid2 })
            await hub.kafkaProducer.flush()
            // Batch 2 - waiting for a few seconds so that the event lands into a separate consumer batch
            await delay(5000)
            await posthog.capture('custom event via buffer', { name: 'hihi', uuid: uuid3 })
            await hub.kafkaProducer.flush()

            const bufferTopicMessages = await delayUntilBufferMessageProduced(3)
            const events = await delayUntilEventIngested(() => hub.db.fetchEvents(), 3, undefined, 200)

            expect(bufferTopicMessages.filter((message) => message.properties.uuid === uuid1).length).toBe(1)
            expect(bufferTopicMessages.filter((message) => message.properties.uuid === uuid2).length).toBe(1)
            expect(bufferTopicMessages.filter((message) => message.properties.uuid === uuid3).length).toBe(1)
            expect(events.length).toBe(3)

            // At least BUFFER_CONVERSION_SECONDS must have elapsed for each event between queuing and saving
            expect(
                DateTime.fromSQL(events[0].created_at, { zone: 'utc' })
                    .diff(DateTime.fromISO(events[0].timestamp))
                    .toMillis()
            ).toBeGreaterThan(hub.BUFFER_CONVERSION_SECONDS * 1000)
            expect(
                DateTime.fromSQL(events[1].created_at, { zone: 'utc' })
                    .diff(DateTime.fromISO(events[1].timestamp))
                    .toMillis()
            ).toBeGreaterThan(hub.BUFFER_CONVERSION_SECONDS * 1000)
            expect(
                DateTime.fromSQL(events[2].created_at, { zone: 'utc' })
                    .diff(DateTime.fromISO(events[2].timestamp))
                    .toMillis()
            ).toBeGreaterThan(hub.BUFFER_CONVERSION_SECONDS * 1000)

            // processEvent ran and modified
            expect(events[0].properties.processed).toEqual('hell yes')
            expect(events[1].properties.processed).toEqual('hell yes')
            expect(events[2].properties.processed).toEqual('hell yes')
            const eventPluginUuids = events.map((event) => event.properties.upperUuid).sort()
            expect(eventPluginUuids).toStrictEqual([uuid1.toUpperCase(), uuid2.toUpperCase(), uuid3.toUpperCase()])

            // onEvent ran
            expect(testConsole.read()).toEqual([
                ['processEvent'],
                ['onEvent', 'custom event via buffer'],
                ['processEvent'],
                ['onEvent', 'custom event via buffer'],
                ['processEvent'],
                ['onEvent', 'custom event via buffer'],
            ])
        })
    })
})
