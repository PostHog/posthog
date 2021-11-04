import { startPluginsServer } from '../src/main/pluginsServer'
import { Hub, LogLevel, PluginsServerConfig } from '../src/types'
import { makePiscina } from '../src/worker/piscina'
import { createPosthog, DummyPostHog } from '../src/worker/vm/extensions/posthog'
import { pluginConfig39 } from './helpers/plugins'
import { getErrorForPluginConfig, resetTestDatabase } from './helpers/sql'
import { delayUntilEventIngested } from './shared/process-event'

jest.setTimeout(60000) // 60 sec timeout

const extraServerConfig: Partial<PluginsServerConfig> = {
    WORKER_CONCURRENCY: 2,
    PLUGINS_CELERY_QUEUE: 'test-plugins-celery-queue-errors',
    CELERY_DEFAULT_QUEUE: 'test-celery-default-queue-errors',
    LOG_LEVEL: LogLevel.Log,
    KAFKA_ENABLED: false,
}

describe('error do not take down ingestion', () => {
    let hub: Hub
    let stopServer: () => Promise<void>
    let posthog: DummyPostHog

    beforeEach(async () => {
        await resetTestDatabase(`
            export async function processEvent (event, { jobs }) {
                if (event.properties.crash === 'throw') {
                    throw new Error('error thrown in plugin')
                } else if (event.properties.crash === 'throw in promise') {
                    void new Promise(() => { throw new Error('error thrown in plugin') }).then(() => {})
                } else if (event.properties.crash === 'reject in promise') {
                    void new Promise((_, rejects) => { rejects(new Error('error thrown in plugin')) }).then(() => {})
                }
                return event
            }
        `)
        const startResponse = await startPluginsServer(extraServerConfig, makePiscina)
        hub = startResponse.hub
        stopServer = startResponse.stop
        posthog = createPosthog(hub, pluginConfig39)

        const redis = await hub.redisPool.acquire()
        await redis.del(hub.PLUGINS_CELERY_QUEUE)
        await redis.del(hub.CELERY_DEFAULT_QUEUE)
        await hub.redisPool.release(redis)
    })

    afterEach(async () => {
        await stopServer()
    })

    test('thrown errors', async () => {
        expect((await hub.db.fetchEvents()).length).toBe(0)
        expect(await getErrorForPluginConfig(pluginConfig39.id)).toBe(null)

        for (let i = 0; i < 4; i++) {
            await posthog.capture('broken event', { crash: 'throw' })
        }

        await delayUntilEventIngested(() => hub.db.fetchEvents(), 4)

        expect((await hub.db.fetchEvents()).length).toBe(4)

        const error2 = await getErrorForPluginConfig(pluginConfig39.id)
        expect(error2.message).toBe('error thrown in plugin')
    })

    test('unhandled promise errors', async () => {
        expect((await hub.db.fetchEvents()).length).toBe(0)
        expect(await getErrorForPluginConfig(pluginConfig39.id)).toBe(null)

        for (let i = 0; i < 4; i++) {
            await posthog.capture('broken event', { crash: 'throw in promise' })
        }

        await delayUntilEventIngested(() => hub.db.fetchEvents(), 4)

        expect((await hub.db.fetchEvents()).length).toBe(4)

        const error2 = await getErrorForPluginConfig(pluginConfig39.id)
        expect(error2.message).toBe('error thrown in plugin')
    })

    test('unhandled promise rejections', async () => {
        expect((await hub.db.fetchEvents()).length).toBe(0)
        expect(await getErrorForPluginConfig(pluginConfig39.id)).toBe(null)

        for (let i = 0; i < 4; i++) {
            await posthog.capture('broken event', { crash: 'reject in promise' })
        }

        await delayUntilEventIngested(() => hub.db.fetchEvents(), 4)

        expect((await hub.db.fetchEvents()).length).toBe(4)

        const error2 = await getErrorForPluginConfig(pluginConfig39.id)
        expect(error2.message).toBe('error thrown in plugin')
    })
})
