import { runScheduledTasks } from '../../../src/main/graphile-worker/schedule'
import { Hub } from '../../../src/types'
import { UUID } from '../../../src/utils/utils'
import { PromiseManager } from '../../../src/worker/vm/promise-manager'

const mockHub: Hub = {
    graphileWorker: {
        enqueue: jest.fn(),
        addJob: jest.fn(),
    } as any,
    instanceId: new UUID('F8B2F832-6639-4596-ABFC-F9664BC88E84'),
    promiseManager: new PromiseManager({ MAX_PENDING_PROMISES_PER_WORKER: 1 } as any),
    JOB_QUEUES: 'fs',
} as Hub

describe('Graphile Worker schedule', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    test('runScheduledTasks()', async () => {
        const mockHubWithPluginSchedule = {
            ...mockHub,
            pluginSchedule: {
                runEveryMinute: [1, 2, 3],
                runEveryHour: [4, 5, 6],
                runEveryDay: [7, 8, 9],
            },
        }

        await runScheduledTasks(mockHubWithPluginSchedule, 'runEveryMinute')

        expect(mockHub.graphileWorker.enqueue).toHaveBeenNthCalledWith(1, 'pluginScheduledTask', {
            pluginConfigId: 1,
            task: 'runEveryMinute',
            timestamp: expect.any(Number),
        })
        expect(mockHub.graphileWorker.enqueue).toHaveBeenNthCalledWith(2, 'pluginScheduledTask', {
            pluginConfigId: 2,
            task: 'runEveryMinute',
            timestamp: expect.any(Number),
        })
        expect(mockHub.graphileWorker.enqueue).toHaveBeenNthCalledWith(3, 'pluginScheduledTask', {
            pluginConfigId: 3,
            task: 'runEveryMinute',
            timestamp: expect.any(Number),
        })

        await runScheduledTasks(mockHubWithPluginSchedule, 'runEveryHour')
        expect(mockHub.graphileWorker.enqueue).toHaveBeenNthCalledWith(4, 'pluginScheduledTask', {
            pluginConfigId: 4,
            task: 'runEveryHour',
            timestamp: expect.any(Number),
        })
        expect(mockHub.graphileWorker.enqueue).toHaveBeenNthCalledWith(5, 'pluginScheduledTask', {
            pluginConfigId: 5,
            task: 'runEveryHour',
            timestamp: expect.any(Number),
        })
        expect(mockHub.graphileWorker.enqueue).toHaveBeenNthCalledWith(6, 'pluginScheduledTask', {
            pluginConfigId: 6,
            task: 'runEveryHour',
            timestamp: expect.any(Number),
        })

        await runScheduledTasks(mockHubWithPluginSchedule, 'runEveryDay')
        expect(mockHub.graphileWorker.enqueue).toHaveBeenNthCalledWith(7, 'pluginScheduledTask', {
            pluginConfigId: 7,
            task: 'runEveryDay',
            timestamp: expect.any(Number),
        })
        expect(mockHub.graphileWorker.enqueue).toHaveBeenNthCalledWith(8, 'pluginScheduledTask', {
            pluginConfigId: 8,
            task: 'runEveryDay',
            timestamp: expect.any(Number),
        })
        expect(mockHub.graphileWorker.enqueue).toHaveBeenNthCalledWith(9, 'pluginScheduledTask', {
            pluginConfigId: 9,
            task: 'runEveryDay',
            timestamp: expect.any(Number),
        })
    })
})
