import { startPluginsServer } from '../src/main/pluginsServer'
import { Hub, LogLevel, PluginsServerConfig } from '../src/types'
import { makePiscina } from '../src/worker/piscina'
import { createPosthog, DummyPostHog } from '../src/worker/vm/extensions/posthog'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from './helpers/clickhouse'
import { resetKafka } from './helpers/kafka'
import { pluginConfig39 } from './helpers/plugins'
import { getErrorForPluginConfig, resetTestDatabase } from './helpers/sql'

jest.setTimeout(60000) // 60 sec timeout

const extraServerConfig: Partial<PluginsServerConfig> = {
    WORKER_CONCURRENCY: 2,
    LOG_LEVEL: LogLevel.Log,
}

describe('error do not take down ingestion', () => {
    let hub: Hub
    let stopServer: () => Promise<void>
    let posthog: DummyPostHog

    beforeAll(async () => {
        await resetKafka()
    })

    beforeEach(async () => {
        await resetTestDatabase(
            `
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
        `,
            extraServerConfig
        )
        await resetTestDatabaseClickhouse(extraServerConfig)
        const startResponse = await startPluginsServer(extraServerConfig, makePiscina)
        hub = startResponse.hub
        stopServer = startResponse.stop
        posthog = createPosthog(hub, pluginConfig39)
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
