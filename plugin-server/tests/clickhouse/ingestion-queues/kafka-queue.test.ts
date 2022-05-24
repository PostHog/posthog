import { KAFKA_EVENTS_PLUGIN_INGESTION } from '../../../src/config/kafka-topics'
import { ServerInstance, startPluginsServer } from '../../../src/main/pluginsServer'
import { LogLevel, PluginsServerConfig } from '../../../src/types'
import { Hub } from '../../../src/types'
import { UUIDT } from '../../../src/utils/utils'
import { makePiscina } from '../../../src/worker/piscina'
import { createPosthog, DummyPostHog } from '../../../src/worker/vm/extensions/posthog'
import { writeToFile } from '../../../src/worker/vm/extensions/test-utils'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../../helpers/clickhouse'
import { resetKafka } from '../../helpers/kafka'
import { pluginConfig39 } from '../../helpers/plugins'
import { resetTestDatabase } from '../../helpers/sql'

const { console: testConsole } = writeToFile

jest.mock('../../../src/utils/status')
jest.setTimeout(70000) // 60 sec timeout

const extraServerConfig: Partial<PluginsServerConfig> = {
    WORKER_CONCURRENCY: 1,
    KAFKA_CONSUMPTION_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION,
    LOG_LEVEL: LogLevel.Log,
    CONVERSION_BUFFER_ENABLED: true,
    BUFFER_CONVERSION_SECONDS: 1,
}

// TODO: merge these tests with postgres/e2e.test.ts
describe.skip('KafkaQueue', () => {
    let hub: Hub
    let stopServer: () => Promise<void>
    let posthog: DummyPostHog
    let pluginServer: ServerInstance

    beforeAll(async () => {
        await resetKafka(extraServerConfig)
    })

    beforeEach(async () => {
        testConsole.reset()
        await resetTestDatabase()
        await resetTestDatabaseClickhouse(extraServerConfig)
        pluginServer = await startPluginsServer(extraServerConfig, makePiscina)
        hub = pluginServer.hub
        piscina = pluginServer.piscina
        stopServer = pluginServer.stop
        posthog = createPosthog(hub, pluginConfig39)
    })

    afterEach(async () => {
        await stopServer()
    })

    test('consumer consumes from both topics - ingestion and buffer', async () => {
        expect((await hub.db.fetchEvents()).length).toBe(0)
        hub.statsd = {
            timing: jest.fn(),
            increment: jest.fn(),
            gauge: jest.fn(),
        } as any

        jest.spyOn(hub.eventsProcessor, 'produceEventToBuffer')

        const uuid = new UUIDT().toString()

        await posthog.capture('custom event', { name: 'haha', uuid, distinct_id: 'some_id' })

        await delayUntilEventIngested(() => hub.db.fetchEvents())

        await hub.kafkaProducer.flush()
        const events = await hub.db.fetchEvents()

        expect(events.length).toEqual(1)

        const statsdTimingCalls = (hub.statsd?.timing as any).mock.calls

        const mainIngestionCalls = statsdTimingCalls.filter(
            (item: string[]) => item[0] === 'kafka_queue.single_ingestion'
        )
        expect(mainIngestionCalls.length).toEqual(1)

        const bufferCalls = statsdTimingCalls.filter((item: string[]) => item[0] === 'kafka_queue.ingest_buffer_event')
        expect(bufferCalls.length).toEqual(1)
    })
})
