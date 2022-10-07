import IORedis from 'ioredis'

import { ONE_HOUR } from '../src/config/constants'
import { GraphileQueue } from '../src/main/job-queues/concurrent/graphile-queue'
import { startPluginsServer } from '../src/main/pluginsServer'
import { LogLevel, PluginsServerConfig } from '../src/types'
import { Hub } from '../src/types'
import { UUIDT } from '../src/utils/utils'
import { makePiscina } from '../src/worker/piscina'
import { createPosthog, DummyPostHog } from '../src/worker/vm/extensions/posthog'
import { writeToFile } from '../src/worker/vm/extensions/test-utils'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from './helpers/clickhouse'
import { resetKafka } from './helpers/kafka'
import { pluginConfig39 } from './helpers/plugins'
import { resetTestDatabase } from './helpers/sql'
const { console: testConsole } = writeToFile

jest.setTimeout(60000) // 60 sec timeout)

const extraServerConfig: Partial<PluginsServerConfig> = {
    WORKER_CONCURRENCY: 1,
    LOG_LEVEL: LogLevel.Log,
    KAFKA_PRODUCER_MAX_QUEUE_SIZE: 100, // The default in tests is 0 but here we specifically want to test batching
    KAFKA_FLUSH_FREQUENCY_MS: 0, // Same as above, but with time
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
    let hub: Hub
    let stopServer: () => Promise<void>
    let posthog: DummyPostHog
    let redis: IORedis.Redis

    beforeEach(async () => {
        testConsole.reset()
        await resetTestDatabase(indexJs)
        await resetTestDatabaseClickhouse(extraServerConfig)
        await resetKafka(extraServerConfig)
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

            await delayUntilEventIngested(() => hub.db.fetchEvents(), undefined, undefined, 500)
            const events = await hub.db.fetchEvents()

            expect(events.length).toBe(1)

            // processEvent ran and modified
            expect(events[0].properties.processed).toEqual('hell yes')
            expect(events[0].properties.upperUuid).toEqual(uuid.toUpperCase())

            // onEvent ran
            expect(testConsole.read()).toEqual([['processEvent'], ['onEvent', 'custom event via buffer']])
        })

        test('handles graphile worker db being down', async () => {
            expect((await hub.db.fetchEvents()).length).toBe(0)

            const uuid = new UUIDT().toString()

            // Setup the GraphileQueue function to raise a connection error.
            // NOTE: We want to retry on connection errors but not on other
            // errors, e.g. programming errors. We don't handle these cases
            // separately at the moment however.
            const graphileQueueEnqueue = jest.spyOn(GraphileQueue.prototype, 'enqueue').mockImplementation(() => {
                const err = new Error('connection refused') as any
                err.name = 'SystemError'
                err.code = 'ECONNREFUSED'
                throw err
            })

            await posthog.capture('custom event via buffer', { name: 'hehe', uuid })
            await hub.kafkaProducer.flush()

            // Wait up to 5 seconds for the mock to be called. Note we abused
            // the delayUntilEventIngested function here.
            await delayUntilEventIngested(() => graphileQueueEnqueue.mock.calls.length, undefined, 100, 50)
            expect(graphileQueueEnqueue.mock.calls.length).toBeGreaterThan(0)
            let events = await hub.db.fetchEvents()
            expect(events.length).toBe(0)

            // Now let's make the GraphileQueue function work again, then wait
            // for the event to be ingested.
            graphileQueueEnqueue.mockRestore()
            await delayUntilEventIngested(() => hub.db.fetchEvents(), undefined, 100, 100)
            events = await hub.db.fetchEvents()
            expect(events.length).toBe(1)
        })
    })
})
