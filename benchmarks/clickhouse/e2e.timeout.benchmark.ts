import { performance } from 'perf_hooks'

import { KAFKA_EVENTS_PLUGIN_INGESTION } from '../../src/ingestion/topics'
import { startPluginsServer } from '../../src/server'
import { ClickHouseEvent, LogLevel, PluginsServerConfig, Queue } from '../../src/types'
import { PluginsServer } from '../../src/types'
import { delay, UUIDT } from '../../src/utils'
import { createPosthog, DummyPostHog } from '../../src/vm/extensions/posthog'
import { makePiscina } from '../../src/worker/piscina'
import { resetTestDatabaseClickhouse } from '../../tests/helpers/clickhouse'
import { resetKafka } from '../../tests/helpers/kafka'
import { pluginConfig39 } from '../../tests/helpers/plugins'
import { resetTestDatabase } from '../../tests/helpers/sql'
import { delayUntilEventIngested } from '../../tests/shared/process-event'

jest.setTimeout(600000) // 10min timeout

const extraServerConfig: Partial<PluginsServerConfig> = {
    KAFKA_ENABLED: true,
    KAFKA_HOSTS: process.env.KAFKA_HOSTS || 'kafka:9092',
    WORKER_CONCURRENCY: 4,
    TASK_TIMEOUT: 5,
    PLUGIN_SERVER_INGESTION: true,
    KAFKA_CONSUMPTION_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_BATCH_PARALELL_PROCESSING: true,
    LOG_LEVEL: LogLevel.Log,
}

describe('e2e kafka processing timeout benchmark', () => {
    let queue: Queue
    let server: PluginsServer
    let stopServer: () => Promise<void>
    let posthog: DummyPostHog

    beforeEach(async () => {
        await resetTestDatabase(`
            async function processEvent (event) {
                await new Promise(resolve => __jestSetTimeout(() => resolve(), 15000 * Math.random()))
                event.properties.timeout = 'no timeout'
                return event
            }
        `)
        await resetKafka(extraServerConfig)
        await resetTestDatabaseClickhouse(extraServerConfig)

        const startResponse = await startPluginsServer(extraServerConfig, makePiscina)
        server = startResponse.server
        stopServer = startResponse.stop
        queue = startResponse.queue

        posthog = createPosthog(server, pluginConfig39)
    })

    afterEach(async () => {
        await stopServer()
    })

    test('measure performance', async () => {
        console.debug = () => null

        const count = 3000

        // fill in the queue
        function createEvent() {
            const uuid = new UUIDT().toString()
            posthog.capture('custom event', { name: 'haha', uuid, randomProperty: 'lololo' })
        }
        await queue.pause()
        for (let i = 0; i < count; i++) {
            createEvent()
        }

        // hope that 5sec is enough to load kafka with all the events (posthog.capture can't be awaited)
        await delay(5000)
        await queue.resume()

        console.log('Starting timer')
        const startTime = performance.now()
        await delayUntilEventIngested(() => server.db.fetchEvents(), count, 500, count)
        const timeMs = performance.now() - startTime
        console.log('Finished!')

        const n = (n: number) => `${Math.round(n * 100) / 100}`
        console.log(
            `ℹ️️ [Kafka & ClickHouse] Ingested ${count} events in ${n(timeMs / 1000)}s (${n(
                1000 / (timeMs / count)
            )} events/sec, ${n(timeMs / count)}ms per event)`
        )
        const events = (await server.db.fetchEvents()) as ClickHouseEvent[]
        const passedEvents = events.filter((e) => e.properties.timeout).length
        console.log(
            `ℹ️ Out of 3000 events: ${passedEvents} took under 5sec, ${
                3000 - passedEvents
            } timed out. This should be a 1:2 ratio.`
        )
    })
})
