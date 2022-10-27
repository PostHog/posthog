import { runScheduledTasks } from '../../../src/main/graphile-worker/schedule'
import { Hub } from '../../../src/types'
import { UUID } from '../../../src/utils/utils'
import { PromiseManager } from '../../../src/worker/vm/promise-manager'

const mockHub: Hub = {
    instanceId: new UUID('F8B2F832-6639-4596-ABFC-F9664BC88E84'),
    promiseManager: new PromiseManager({ MAX_PENDING_PROMISES_PER_WORKER: 1 } as any),
    JOB_QUEUES: 'fs',
} as Hub

describe('Graphile Worker schedule', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    test('runScheduledTasks()', async () => {
        const mockPiscina = {
            run: jest.fn(),
        }

        const mockHubWithPluginSchedule = {
            ...mockHub,
            pluginSchedule: {
                runEveryMinute: [1, 2, 3],
                runEveryHour: [4, 5, 6],
                runEveryDay: [7, 8, 9],
            },
        }

        await runScheduledTasks(mockHubWithPluginSchedule, mockPiscina as any, 'iDontExist')
        expect(mockPiscina.run).not.toHaveBeenCalled()

        await runScheduledTasks(mockHubWithPluginSchedule, mockPiscina as any, 'runEveryMinute')

        expect(mockPiscina.run).toHaveBeenNthCalledWith(1, { args: { pluginConfigId: 1 }, task: 'runEveryMinute' })
        expect(mockPiscina.run).toHaveBeenNthCalledWith(2, { args: { pluginConfigId: 2 }, task: 'runEveryMinute' })
        expect(mockPiscina.run).toHaveBeenNthCalledWith(3, { args: { pluginConfigId: 3 }, task: 'runEveryMinute' })

        await runScheduledTasks(mockHubWithPluginSchedule, mockPiscina as any, 'runEveryHour')
        expect(mockPiscina.run).toHaveBeenNthCalledWith(4, { args: { pluginConfigId: 4 }, task: 'runEveryHour' })
        expect(mockPiscina.run).toHaveBeenNthCalledWith(5, { args: { pluginConfigId: 5 }, task: 'runEveryHour' })
        expect(mockPiscina.run).toHaveBeenNthCalledWith(6, { args: { pluginConfigId: 6 }, task: 'runEveryHour' })

        await runScheduledTasks(mockHubWithPluginSchedule, mockPiscina as any, 'runEveryDay')
        expect(mockPiscina.run).toHaveBeenNthCalledWith(7, { args: { pluginConfigId: 7 }, task: 'runEveryDay' })
        expect(mockPiscina.run).toHaveBeenNthCalledWith(8, { args: { pluginConfigId: 8 }, task: 'runEveryDay' })
        expect(mockPiscina.run).toHaveBeenNthCalledWith(9, { args: { pluginConfigId: 9 }, task: 'runEveryDay' })
    })
})
