import { performance } from 'perf_hooks'

import { createPosthog, DummyPostHog } from '../../src/extensions/posthog'
import { KAFKA_EVENTS_PLUGIN_INGESTION } from '../../src/ingestion/topics'
import { startPluginsServer } from '../../src/server'
import { LogLevel, PluginsServerConfig, Queue } from '../../src/types'
import { PluginsServer } from '../../src/types'
import { delay, UUIDT } from '../../src/utils'
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
    PLUGIN_SERVER_INGESTION: true,
    KAFKA_CONSUMPTION_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_BATCH_PARALELL_PROCESSING: true,
    LOG_LEVEL: LogLevel.Log,
}

describe('e2e kafka & clickhouse benchmark', () => {
    let queue: Queue
    let server: PluginsServer
    let stopServer: () => Promise<void>
    let posthog: DummyPostHog

    beforeEach(async () => {
        await resetTestDatabase(`
            async function processEventBatch (batch) {
                // console.log(\`Received batch of \${batch.length} events\`)
                return batch.map(event => {
                    event.properties.processed = 'hell yes'
                    event.properties.upperUuid = event.properties.uuid?.toUpperCase()
                    return event
                })
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
            `[Kafka & ClickHouse] Ingested ${count} events in ${n(timeMs / 1000)}s (${n(
                1000 / (timeMs / count)
            )} events/sec, ${n(timeMs / count)}ms per event)`
        )

        const events = await server.db.fetchEvents()
        expect(events[count - 1].properties.upperUuid).toEqual(events[count - 1].properties.uuid.toUpperCase())
    })
})
