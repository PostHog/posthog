import * as IORedis from 'ioredis'
import { performance } from 'perf_hooks'

import { startPluginsServer } from '../../src/main/pluginsServer'
import { Hub, LogLevel, PluginsServerConfig, Queue } from '../../src/types'
import { delay, UUIDT } from '../../src/utils/utils'
import { makePiscina } from '../../src/worker/piscina'
import { createPosthog, DummyPostHog } from '../../src/worker/vm/extensions/posthog'
import { pluginConfig39 } from '../../tests/helpers/plugins'
import { resetTestDatabase } from '../../tests/helpers/sql'
import { delayUntilEventIngested } from '../../tests/shared/process-event'

jest.setTimeout(600000) // 10min timeout

const extraServerConfig: Partial<PluginsServerConfig> = {
    WORKER_CONCURRENCY: 4,
    REDIS_POOL_MIN_SIZE: 3,
    REDIS_POOL_MAX_SIZE: 3,
    PLUGINS_CELERY_QUEUE: 'test-plugins-celery-queue',
    CELERY_DEFAULT_QUEUE: 'test-celery-default-queue',
    LOG_LEVEL: LogLevel.Log,
    KAFKA_ENABLED: false,
}

describe('e2e celery & postgres benchmark', () => {
    let queue: Queue
    let hub: Hub
    let stopServer: () => Promise<void>
    let posthog: DummyPostHog
    let redis: IORedis.Redis

    beforeEach(async () => {
        await resetTestDatabase(`
            async function processEvent (event) {
                event.properties.processed = 'hell yes'
                event.properties.upperUuid = event.properties.uuid?.toUpperCase()
                return event
            }
        `)

        const startResponse = await startPluginsServer(extraServerConfig, makePiscina)
        hub = startResponse.hub
        stopServer = startResponse.stop
        queue = startResponse.queue
        redis = await hub.redisPool.acquire()

        await redis.del(hub.PLUGINS_CELERY_QUEUE)
        await redis.del(hub.CELERY_DEFAULT_QUEUE)

        posthog = createPosthog(hub, pluginConfig39)
    })

    afterEach(async () => {
        await hub.redisPool.release(redis)
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
        await queue.pause()
        expect(await redis.llen(hub.PLUGINS_CELERY_QUEUE)).toEqual(0)
        for (let i = 0; i < count; i++) {
            await createEvent()
        }
        await delay(3000)
        expect(await redis.llen(hub.PLUGINS_CELERY_QUEUE)).toEqual(count)
        await queue.resume()

        console.log('Starting timer')
        const startTime = performance.now()
        await delayUntilEventIngested(() => hub.db.fetchEvents(), count, 500, count)
        const timeMs = performance.now() - startTime
        console.log('Finished!')

        const n = (n: number) => `${Math.round(n * 100) / 100}`
        console.log(
            `[Celery & Postgres] Ingested ${count} events in ${n(timeMs / 1000)}s (${n(
                1000 / (timeMs / count)
            )} events/sec, ${n(timeMs / count)}ms per event)`
        )

        const events = await hub.db.fetchEvents()
        expect(events[count - 1].properties.upperUuid).toEqual(events[count - 1].properties.uuid.toUpperCase())
    })
})
