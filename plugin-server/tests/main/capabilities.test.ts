import { GraphileWorker } from '../../src/main/graphile-worker/graphile-worker'
import { startGraphileWorker } from '../../src/main/graphile-worker/worker-setup'
import { IngestionConsumer } from '../../src/main/ingestion-queues/kafka-queue'
import { startQueues } from '../../src/main/ingestion-queues/queue'
import { Hub, LogLevel } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'

jest.mock('../../src/main/ingestion-queues/kafka-queue')
jest.mock('../../src/main/graphile-worker/schedule')

describe('capabilities', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub({
            LOG_LEVEL: LogLevel.Warn,
        })
    })

    afterEach(async () => {
        await closeHub()
    })

    describe('queue', () => {
        it('starts ingestion queue by default', async () => {
            const queues = await startQueues(hub)

            expect(queues).toEqual({
                ingestion: expect.any(IngestionConsumer),
            })
        })

        it('handles ingestion being turned off', async () => {
            hub.capabilities.ingestion = false
            hub.capabilities.processAsyncHandlers = false

            const queues = await startQueues(hub)

            expect(queues).toEqual({
                ingestion: null,
            })
        })
    })

    describe('startGraphileWorker()', () => {
        it('sets up bufferJob handler if ingestion is on', async () => {
            const graphileWorker = new GraphileWorker(hub)
            jest.spyOn(hub.graphileWorker, 'start').mockImplementation(jest.fn())
            hub.capabilities.ingestion = true
            hub.capabilities.processPluginJobs = false
            hub.capabilities.pluginScheduledTasks = false

            await startGraphileWorker(hub, graphileWorker)

            expect(hub.graphileWorker.start).toHaveBeenCalledWith(
                {
                    bufferJob: expect.anything(),
                },
                []
            )
        })

        it('sets up pluginJob handler if processPluginJobs is on', async () => {
            const graphileWorker = new GraphileWorker(hub)
            jest.spyOn(graphileWorker, 'start').mockImplementation(jest.fn())
            hub.capabilities.ingestion = false
            hub.capabilities.processPluginJobs = true
            hub.capabilities.pluginScheduledTasks = false

            await startGraphileWorker(hub, graphileWorker)

            expect(hub.graphileWorker.start).toHaveBeenCalledWith(
                {
                    pluginJob: expect.anything(),
                },
                []
            )
        })

        it('sets up bufferJob and pluginJob handlers if ingestion and processPluginJobs are on', async () => {
            const graphileWorker = new GraphileWorker(hub)
            jest.spyOn(hub.graphileWorker, 'start').mockImplementation(jest.fn())
            hub.capabilities.ingestion = true
            hub.capabilities.processPluginJobs = true
            hub.capabilities.pluginScheduledTasks = false

            await startGraphileWorker(hub, graphileWorker)

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

            await startGraphileWorker(hub, graphileWorker)

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
