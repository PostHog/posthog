import Piscina from '@posthog/piscina'
import { PluginEvent } from '@posthog/plugin-scaffold'

import { defaultConfig } from '../src/config/config'
import { startPluginsServer } from '../src/main/pluginsServer'
import { EnqueuedPluginJob, LogLevel, PluginsServerConfig } from '../src/types'
import { Hub } from '../src/types'
import { UUIDT } from '../src/utils/utils'
import { EventPipelineRunner } from '../src/worker/ingestion/event-pipeline/runner'
import { makePiscina } from '../src/worker/piscina'
import { writeToFile } from '../src/worker/vm/extensions/test-utils'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from './helpers/clickhouse'
import { resetGraphileWorkerSchema } from './helpers/graphile-worker'
import { resetKafka } from './helpers/kafka'
import { pluginConfig39 } from './helpers/plugins'
import { resetTestDatabase } from './helpers/sql'

jest.mock('../src/utils/status')
jest.setTimeout(60000) // 60 sec timeout

const { console: testConsole } = writeToFile

const extraServerConfig: Partial<PluginsServerConfig> = {
    WORKER_CONCURRENCY: 2,
    LOG_LEVEL: LogLevel.Log,
    CONVERSION_BUFFER_ENABLED: false,
    HISTORICAL_EXPORTS_ENABLED: true,
    HISTORICAL_EXPORTS_FETCH_WINDOW_MULTIPLIER: 2,
    HISTORICAL_EXPORTS_INITIAL_FETCH_TIME_WINDOW: 8 * 60 * 60 * 1000, // 8 hours
}

const indexJs = `
import { console as testConsole } from 'test-utils/write-to-file'

export async function exportEvents(events) {
    for (const event of events) {
        if (event.properties && event.properties['$$is_historical_export_event']) {
            testConsole.log('exported historical event', event)
        }
    }
}
`

describe('Historical Export (v2)', () => {
    let hub: Hub
    let stopServer: () => Promise<void>
    let piscina: Piscina

    beforeAll(async () => {
        await resetKafka(extraServerConfig)
    })

    beforeEach(async () => {
        console.info = jest.fn()

        testConsole.reset()
        await Promise.all([
            await resetTestDatabase(indexJs),
            await resetTestDatabaseClickhouse(extraServerConfig),
            await resetGraphileWorkerSchema(defaultConfig),
        ])

        const startResponse = await startPluginsServer(extraServerConfig, makePiscina)
        hub = startResponse.hub
        piscina = startResponse.piscina
        stopServer = startResponse.stop
    })

    afterEach(async () => {
        await stopServer()
    })

    async function ingestEvent(timestamp: string, overrides: Partial<PluginEvent> = {}) {
        const pluginEvent: PluginEvent = {
            event: 'some_event',
            distinct_id: 'some_user',
            site_url: '',
            team_id: 2,
            timestamp: timestamp,
            now: timestamp,
            ip: '',
            uuid: new UUIDT().toString(),
            ...overrides,
        } as any as PluginEvent

        const runner = new EventPipelineRunner(hub, pluginEvent)
        await runner.runEventPipeline(pluginEvent)
    }

    it('exports a batch of events in a time range', async () => {
        await Promise.all([
            ingestEvent('2021-07-28T00:00:00.000Z'),
            ingestEvent('2021-08-01T00:00:00.000Z', { properties: { foo: 'bar' } }),
            ingestEvent('2021-08-02T02:00:00.000Z'),
            ingestEvent('2021-08-03T09:00:00.000Z'),
            ingestEvent('2021-08-03T15:00:00.000Z'),
            ingestEvent('2021-08-04T23:00:00.000Z'),
            ingestEvent('2021-08-04T23:59:59.000Z'),
            ingestEvent('2021-08-05T00:00:00.000Z'),
            ingestEvent('2021-08-05T01:00:00.000Z'),
        ])

        await hub.kafkaProducer.flush()
        await delayUntilEventIngested(() => hub.db.fetchEvents(), 9)

        await piscina.run({
            task: 'runPluginJob',
            args: {
                job: {
                    type: 'Export historical events V2',
                    payload: {
                        dateRange: ['2021-08-01', '2021-08-04'],
                        parallelism: 5,
                        $operation: 'start',
                    },
                    pluginConfigId: pluginConfig39.id,
                    pluginConfigTeam: pluginConfig39.team_id,
                    timestamp: 0,
                } as EnqueuedPluginJob,
            },
        })

        await delayUntilEventIngested(() => Promise.resolve(testConsole.read()), 6, 1000, 50)

        const exportedEventLogs = testConsole.read() as Array<[string, any]>
        exportedEventLogs.sort((e1, e2) => e1[1].timestamp.localeCompare(e2[1].timestamp))

        const timestamps = exportedEventLogs.map(([, event]) => event.timestamp)
        expect(timestamps).toEqual([
            '2021-08-01T00:00:00.000Z',
            '2021-08-02T02:00:00.000Z',
            '2021-08-03T09:00:00.000Z',
            '2021-08-03T15:00:00.000Z',
            '2021-08-04T23:00:00.000Z',
            '2021-08-04T23:59:59.000Z',
        ])
        expect(exportedEventLogs[0][1].properties).toEqual({
            foo: 'bar',
            $$historical_export_source_db: 'clickhouse',
            $$is_historical_export_event: true,
            $$historical_export_timestamp: expect.any(String),
        })
    })
})
