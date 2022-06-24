import IORedis from 'ioredis'

import { ONE_HOUR } from '../src/config/constants'
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

jest.mock('../src/utils/status')
jest.setTimeout(60000) // 60 sec timeout

const extraServerConfig: Partial<PluginsServerConfig> = {
    WORKER_CONCURRENCY: 2,
    LOG_LEVEL: LogLevel.Log,
    BUFFER_CONVERSION_SECONDS: 1, // We want to test the delay mechanism, but with a much lower delay than in prod
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

export async function onAction(action, event) {
    testConsole.log('onAction', action, event)
}


export async function runEveryMinute() {}
`

describe('E2E with buffer enabled', () => {
    let hub: Hub
    let stopServer: () => Promise<void>
    let posthog: DummyPostHog
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

            await delayUntilEventIngested(() => hub.db.fetchEvents())

            await hub.kafkaProducer.flush()
            const events = await hub.db.fetchEvents()

            expect(events.length).toBe(1)

            // processEvent ran and modified
            expect(events[0].properties.processed).toEqual('hell yes')
            expect(events[0].properties.upperUuid).toEqual(uuid.toUpperCase())

            // onEvent ran
            expect(testConsole.read()).toEqual([['processEvent'], ['onEvent', 'custom event via buffer']])
        })
    })
})
