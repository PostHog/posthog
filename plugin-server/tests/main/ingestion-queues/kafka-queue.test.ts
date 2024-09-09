import { Assignment } from 'node-rdkafka'

import { KAFKA_EVENTS_PLUGIN_INGESTION } from '../../../src/config/kafka-topics'
import { countPartitionsPerTopic } from '../../../src/kafka/consumer'
import { ServerInstance, startPluginsServer } from '../../../src/main/pluginsServer'
import { LogLevel, PluginsServerConfig } from '../../../src/types'
import { Hub } from '../../../src/types'
import { UUIDT } from '../../../src/utils/utils'
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
}

// TODO: merge these tests with postgres/e2e.test.ts
describe.skip('IngestionConsumer', () => {
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
        pluginServer = await startPluginsServer(extraServerConfig)
        hub = pluginServer.hub
        stopServer = pluginServer.stop
        posthog = createPosthog(hub, pluginConfig39)
    })

    afterEach(async () => {
        await stopServer()
    })

    test('consumer consumes from both topics - ingestion and buffer', async () => {
        expect((await hub.db.fetchEvents()).length).toBe(0)

        const uuid = new UUIDT().toString()

        await posthog.capture('custom event', { name: 'haha', uuid, distinct_id: 'some_id' })

        await delayUntilEventIngested(() => hub.db.fetchEvents())

        await hub.kafkaProducer.flush()
        const events = await hub.db.fetchEvents()

        expect(events.length).toEqual(1)
    })
})

describe('countPartitionsPerTopic', () => {
    it('should correctly count the number of partitions per topic', () => {
        const assignments: Assignment[] = [
            { topic: 'topic1', partition: 0 },
            { topic: 'topic1', partition: 1 },
            { topic: 'topic2', partition: 0 },
            { topic: 'topic2', partition: 1 },
            { topic: 'topic2', partition: 2 },
            { topic: 'topic3', partition: 0 },
        ]

        const result = countPartitionsPerTopic(assignments)
        expect(result.get('topic1')).toBe(2)
        expect(result.get('topic2')).toBe(3)
        expect(result.get('topic3')).toBe(1)
        expect(result.size).toBe(3)
    })
})
