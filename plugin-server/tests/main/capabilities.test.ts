import { GraphileWorker } from '../../src/main/graphile-worker/graphile-worker'
import { startGraphileWorker } from '../../src/main/graphile-worker/worker-setup'
import { Hub, LogLevel } from '../../src/types'
import { PluginServerMode, stringToPluginServerMode } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { status } from '../../src/utils/status'
import Piscina from '../../src/worker/piscina'

jest.mock('../../src/main/ingestion-queues/kafka-queue')
jest.mock('../../src/main/graphile-worker/schedule')
jest.mock('../../src/utils/status')

describe('stringToPluginServerMode', () => {
    test('gives the right value for async -> PluginServerMode.plugins_async', () => {
        expect(stringToPluginServerMode['async']).toEqual(PluginServerMode.plugins_async)
    })

    test('gives undefined for invalid input', () => {
        expect(stringToPluginServerMode['invalid']).toEqual(undefined)
    })
})

describe('capabilities', () => {
    let hub: Hub
    let piscina: Piscina
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub({
            LOG_LEVEL: LogLevel.Warn,
        })
        piscina = { run: jest.fn(), on: jest.fn() } as any
    })

    afterEach(async () => {
        await closeHub()
    })

    describe('recordings ingestion', () => {
        it('starts with default config and warns', () => {
            expect(hub.capabilities.sessionRecordingIngestion).toBeTruthy()
            expect(hub.capabilities.sessionRecordingBlobIngestion).toBeTruthy()

            expect((status.warn as any).mock.calls).toEqual([
                [
                    '⚠️',
                    'SESSION_RECORDING_ALLOW_V1_INGESTION is deprecated and will be removed. You must setup blob storage. Future versions of PostHog will not support storing recordings in ClickHouse.',
                ],
            ])
        })

        it('can be disabled by config', async () => {
            ;[hub, closeHub] = await createHub({
                SESSION_RECORDING_ALLOW_V1_INGESTION: false,
                LOG_LEVEL: LogLevel.Warn,
            })
            ;(status.warn as any).mockClear()

            expect(hub.capabilities.sessionRecordingIngestion).toBeFalsy()
            expect(hub.capabilities.sessionRecordingBlobIngestion).toBeTruthy()

            expect((status.warn as any).mock.calls).toEqual([])
        })
    })

    describe('startGraphileWorker()', () => {
        it('sets up pluginJob handler if processPluginJobs is on', async () => {
            const graphileWorker = new GraphileWorker(hub)
            jest.spyOn(graphileWorker, 'start').mockImplementation(jest.fn())
            hub.capabilities.ingestion = false
            hub.capabilities.processPluginJobs = true
            hub.capabilities.pluginScheduledTasks = false

            await startGraphileWorker(hub, graphileWorker, piscina)

            expect(graphileWorker.start).toHaveBeenCalledWith(
                {
                    pluginJob: expect.anything(),
                },
                []
            )
        })

        it('sets up scheduled task handlers if pluginScheduledTasks is on', async () => {
            const graphileWorker = new GraphileWorker(hub)
            jest.spyOn(graphileWorker, 'start').mockImplementation(jest.fn())

            hub.capabilities.ingestion = false
            hub.capabilities.processPluginJobs = false
            hub.capabilities.pluginScheduledTasks = true

            await startGraphileWorker(hub, graphileWorker, piscina)

            expect(graphileWorker.start).toHaveBeenCalledWith(
                {
                    runEveryMinute: expect.anything(),
                    runEveryHour: expect.anything(),
                    runEveryDay: expect.anything(),
                },
                [
                    {
                        identifier: 'runEveryMinute',
                        options: {
                            backfillPeriod: 0,
                            maxAttempts: 1,
                        },
                        pattern: '* * * * *',
                        task: 'runEveryMinute',
                    },
                    {
                        identifier: 'runEveryHour',
                        options: {
                            backfillPeriod: 0,
                            maxAttempts: 5,
                        },
                        pattern: '0 * * * *',
                        task: 'runEveryHour',
                    },
                    {
                        identifier: 'runEveryDay',
                        options: {
                            backfillPeriod: 0,
                            maxAttempts: 10,
                        },
                        pattern: '0 0 * * *',
                        task: 'runEveryDay',
                    },
                ]
            )
        })
    })
})
