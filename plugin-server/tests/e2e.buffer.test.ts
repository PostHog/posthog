import assert from 'assert'

import { ONE_HOUR } from '../src/config/constants'
import { startPluginsServer } from '../src/main/pluginsServer'
import { LogLevel, PluginsServerConfig } from '../src/types'
import { Hub } from '../src/types'
import { UUIDT } from '../src/utils/utils'
import { makePiscina } from '../src/worker/piscina'
import { createPosthog, DummyPostHog } from '../src/worker/vm/extensions/posthog'
import { writeToFile } from '../src/worker/vm/extensions/test-utils'
import { delayUntilEventIngested } from './helpers/clickhouse'
import { fetchEvents } from './helpers/events'
import { resetTestDatabase } from './helpers/sql'
const { console: testConsole } = writeToFile

jest.setTimeout(20000) // 60 sec timeout

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

describe('E2E with buffer topic enabled', () => {
    let hub: Hub
    let stopServer: (() => Promise<void>) | undefined
    let posthog: DummyPostHog
    let teamId: number

    const extraServerConfig: Partial<PluginsServerConfig> = {
        WORKER_CONCURRENCY: 1,
        LOG_LEVEL: LogLevel.Log,
        KAFKA_PRODUCER_MAX_QUEUE_SIZE: 100, // The default in tests is 0 but here we specifically want to test batching
        KAFKA_FLUSH_FREQUENCY_MS: 0, // Same as above, but with time
        BUFFER_CONVERSION_SECONDS: 3, // We want to test the delay mechanism, but with a much lower delay than in prod
        CONVERSION_BUFFER_ENABLED: true,
    }

    beforeEach(async () => {
        testConsole.reset()
        ;({ teamId } = await resetTestDatabase(indexJs))
        const startResponse = await startPluginsServer(
            { ...extraServerConfig, CONVERSION_BUFFER_TOPIC_ENABLED_TEAMS: teamId.toString() },
            makePiscina,
            { ingestion: true, processAsyncHandlers: true }
        )
        assert(startResponse.hub)
        hub = startResponse.hub
        stopServer = startResponse.stop
        posthog = createPosthog(hub, teamId)
    })

    afterEach(async () => {
        await stopServer?.()
    })

    describe('ClickHouse ingestion', () => {
        test('event captured, processed, ingested', async () => {
            expect((await fetchEvents(teamId)).length).toBe(0)

            const uuid = new UUIDT().toString()

            await posthog.capture('custom event via buffer', { name: 'hehe', uuid })
            await hub.kafkaProducer.flush()

            await delayUntilEventIngested(() => fetchEvents(teamId), 1, 1000, 20)
            const events = await fetchEvents(teamId)

            expect(events.length).toBe(1)

            // processEvent ran and modified
            expect(events[0].properties.processed).toEqual('hell yes')
            expect(events[0].properties.upperUuid).toEqual(uuid.toUpperCase())

            // onEvent ran
            expect(testConsole.read()).toEqual([['processEvent'], ['onEvent', 'custom event via buffer']])
        })
    })
})

describe('E2E with direct to graphile worker', () => {
    let hub: Hub
    let stopServer: (() => Promise<void>) | undefined
    let posthog: DummyPostHog
    let teamId: number

    const extraServerConfig: Partial<PluginsServerConfig> = {
        WORKER_CONCURRENCY: 1,
        LOG_LEVEL: LogLevel.Log,
        KAFKA_PRODUCER_MAX_QUEUE_SIZE: 100, // The default in tests is 0 but here we specifically want to test batching
        KAFKA_FLUSH_FREQUENCY_MS: 0, // Same as above, but with time
        BUFFER_CONVERSION_SECONDS: 3, // We want to test the delay mechanism, but with a much lower delay than in prod
        CONVERSION_BUFFER_ENABLED: true,
        CONVERSION_BUFFER_TOPIC_ENABLED_TEAMS: '',
    }

    beforeEach(async () => {
        testConsole.reset()
        ;({ teamId } = await resetTestDatabase(indexJs))
        const startResponse = await startPluginsServer(
            { ...extraServerConfig, CONVERSION_BUFFER_TOPIC_ENABLED_TEAMS: teamId.toString() },
            makePiscina,
            { ingestion: true, processAsyncHandlers: true }
        )
        assert(startResponse.hub)
        hub = startResponse.hub
        stopServer = startResponse.stop
        posthog = createPosthog(hub, teamId)
    })

    afterEach(async () => {
        await stopServer?.()
    })

    describe('ClickHouse ingestion', () => {
        test('event captured, processed, ingested', async () => {
            expect((await fetchEvents(teamId)).length).toBe(0)

            const uuid = new UUIDT().toString()

            await posthog.capture('custom event via buffer', { name: 'hehe', uuid })
            await hub.kafkaProducer.flush()

            await delayUntilEventIngested(() => fetchEvents(teamId), 1, 1000, 20)
            const events = await fetchEvents(teamId)

            expect(events.length).toBe(1)

            // processEvent ran and modified
            expect(events[0].properties.processed).toEqual('hell yes')
            expect(events[0].properties.upperUuid).toEqual(uuid.toUpperCase())

            // onEvent ran
            expect(testConsole.read()).toEqual([['processEvent'], ['onEvent', 'custom event via buffer']])
        })
    })
})
