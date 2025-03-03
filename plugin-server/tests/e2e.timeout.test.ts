import { KAFKA_EVENTS_PLUGIN_INGESTION } from '../src/config/kafka-topics'
import { PluginServer } from '../src/server'
import { LogLevel, PluginServerMode, PluginsServerConfig } from '../src/types'
import { delay, UUIDT } from '../src/utils/utils'
import { createPosthog, DummyPostHog } from '../src/worker/vm/extensions/posthog'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from './helpers/clickhouse'
import { resetKafka } from './helpers/kafka'
import { pluginConfig39 } from './helpers/plugins'
import { resetTestDatabase } from './helpers/sql'

jest.setTimeout(60000) // 60 sec timeout

const extraServerConfig: Partial<PluginsServerConfig> = {
    TASK_TIMEOUT: 2,
    KAFKA_CONSUMPTION_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION,
    LOG_LEVEL: LogLevel.Log,
    PLUGIN_SERVER_MODE: PluginServerMode.ingestion_v2,
}

describe('e2e ingestion timeout', () => {
    let server: PluginServer
    let posthog: DummyPostHog

    beforeAll(async () => {
        await resetKafka(extraServerConfig)
    })

    beforeEach(async () => {
        jest.spyOn(process, 'exit').mockImplementation()
        await resetTestDatabase(`
            async function processEvent (event) {
                await new Promise(resolve => __jestSetTimeout(() => resolve(), 800))
                await new Promise(resolve => __jestSetTimeout(() => resolve(), 800))
                await new Promise(resolve => __jestSetTimeout(() => resolve(), 800))
                await new Promise(resolve => __jestSetTimeout(() => resolve(), 800))
                await new Promise(resolve => __jestSetTimeout(() => resolve(), 800))
                event.properties = { passed: true }
                return event
            }
        `)
        await resetTestDatabaseClickhouse(extraServerConfig)
        server = new PluginServer(extraServerConfig)
        await server.start()

        posthog = createPosthog(server.hub!, pluginConfig39)
    })

    afterEach(async () => {
        await server.stop()
    })

    test('event captured, processed, ingested', async () => {
        expect((await server.hub!.db.fetchEvents()).length).toBe(0)
        const uuid = new UUIDT().toString()
        await posthog.capture('custom event', { name: 'haha', uuid, randomProperty: 'lololo' })
        await delayUntilEventIngested(() => server.hub!.db.fetchEvents())

        await server.hub!.kafkaProducer.flush()
        const events = await server.hub!.db.fetchEvents()
        await delay(1000)

        expect(events.length).toBe(1)
        expect(events[0].properties.name).toEqual('haha')
        expect(events[0].properties.passed).not.toEqual(true)
    })
})
