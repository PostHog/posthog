import { performance } from 'perf_hooks'

import { KAFKA_EVENTS_PLUGIN_INGESTION } from '../../src/config/kafka-topics'
import { KafkaQueue } from '../../src/main/ingestion-queues/kafka-queue'
import { startPluginsServer } from '../../src/main/pluginsServer'
import { Hub, LogLevel, PluginsServerConfig } from '../../src/types'
import { delay, UUIDT } from '../../src/utils/utils'
import { makePiscina } from '../../src/worker/piscina'
import { createPosthog, DummyPostHog } from '../../src/worker/vm/extensions/posthog'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../../tests/helpers/clickhouse'
import { resetKafka } from '../../tests/helpers/kafka'
import { pluginConfig39 } from '../../tests/helpers/plugins'
import { resetTestDatabase } from '../../tests/helpers/sql'

jest.setTimeout(600000) // 10min timeout

const extraServerConfig: Partial<PluginsServerConfig> = {
    WORKER_CONCURRENCY: 4,
    KAFKA_CONSUMPTION_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_BATCH_PARALELL_PROCESSING: true,
    LOG_LEVEL: LogLevel.Log,
}

describe('e2e kafka & clickhouse benchmark', () => {
    let queue: KafkaQueue
    let hub: Hub
    let stopServer: () => Promise<void>
    let posthog: DummyPostHog

    beforeEach(async () => {
        await resetTestDatabase(`
            async function processEvent (event) {
                event.properties.processed = 'hell yes'
                event.properties.upperUuid = event.properties.uuid?.toUpperCase()
                return event
            }
        `)
        await resetKafka(extraServerConfig)
        await resetTestDatabaseClickhouse(extraServerConfig)

        const startResponse = await startPluginsServer(extraServerConfig, makePiscina)
        hub = startResponse.hub
        stopServer = startResponse.stop
        queue = startResponse.queue!

        posthog = createPosthog(hub, pluginConfig39)
    })

    afterEach(async () => {
        await stopServer()
    })

    test('measure performance', async () => {
        console.debug = () => null

        const count = 3000

        // fill in the queue
        async function createEvent() {
            const uuid = new UUIDT().toString()
            await posthog.capture('custom event', { name: 'haha', uuid, randomProperty: 'lololo' })
        }
        await queue.pause(hub.KAFKA_CONSUMPTION_TOPIC)
        for (let i = 0; i < count; i++) {
            await createEvent()
        }

        // hope that 5sec is enough to load kafka with all the events (posthog.capture can't be awaited)
        await delay(5000)
        queue.resume(hub.KAFKA_CONSUMPTION_TOPIC)

        console.log('Starting timer')
        const startTime = performance.now()
        await delayUntilEventIngested(() => hub.db.fetchEvents(), count, 500, count)
        const timeMs = performance.now() - startTime
        console.log('Finished!')

        const n = (n: number) => `${Math.round(n * 100) / 100}`
        console.log(
            `ℹ️️ [Kafka & ClickHouse] Ingested ${count} events in ${n(timeMs / 1000)}s (${n(
                1000 / (timeMs / count)
            )} events/sec, ${n(timeMs / count)}ms per event)`
        )

        const events = await hub.db.fetchEvents()
        expect(events[count - 1].properties.upperUuid).toEqual(events[count - 1].properties.uuid.toUpperCase())
    })
})
