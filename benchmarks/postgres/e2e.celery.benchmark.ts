import { performance } from 'perf_hooks'

import { createPosthog, DummyPostHog } from '../../src/extensions/posthog'
import { startPluginsServer } from '../../src/server'
import { LogLevel, PluginsServerConfig, Queue } from '../../src/types'
import { PluginsServer } from '../../src/types'
import { delay, UUIDT } from '../../src/utils'
import { makePiscina } from '../../src/worker/piscina'
import { pluginConfig39 } from '../../tests/helpers/plugins'
import { resetTestDatabase } from '../../tests/helpers/sql'
import { delayUntilEventIngested } from '../../tests/shared/process-event'

jest.setTimeout(600000) // 10min timeout

const extraServerConfig: Partial<PluginsServerConfig> = {
    WORKER_CONCURRENCY: 4,
    PLUGINS_CELERY_QUEUE: 'test-plugins-celery-queue',
    CELERY_DEFAULT_QUEUE: 'test-celery-default-queue',
    PLUGIN_SERVER_INGESTION: true,
    LOG_LEVEL: LogLevel.Log,
    KAFKA_ENABLED: false,
}

describe('e2e celery & postgres benchmark', () => {
    let queue: Queue
    let server: PluginsServer
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

        const startResponse = await startPluginsServer(extraServerConfig, makePiscina)
        server = startResponse.server
        stopServer = startResponse.stop
        queue = startResponse.queue

        await server.redis.del(server.PLUGINS_CELERY_QUEUE)
        await server.redis.del(server.CELERY_DEFAULT_QUEUE)

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
        expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toEqual(0)
        for (let i = 0; i < count; i++) {
            await createEvent()
        }
        await delay(1000)
        expect(await server.redis.llen(server.PLUGINS_CELERY_QUEUE)).toEqual(count)
        await queue.resume()

        console.log('Starting timer')
        const startTime = performance.now()
        await delayUntilEventIngested(() => server.db.fetchEvents(), count, 500, count)
        const timeMs = performance.now() - startTime
        console.log('Finished!')

        const n = (n: number) => `${Math.round(n * 100) / 100}`
        console.log(
            `[Celery & Postgres] Ingested ${count} events in ${n(timeMs / 1000)}s (${n(
                1000 / (timeMs / count)
            )} events/sec, ${n(timeMs / count)}ms per event)`
        )

        const events = await server.db.fetchEvents()
        expect(events[count - 1].properties.upperUuid).toEqual(events[count - 1].properties.uuid.toUpperCase())
    })
})
