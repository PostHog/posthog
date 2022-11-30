import { Producer } from 'kafkajs'

import { runScheduledTasks } from '../../../src/main/graphile-worker/schedule'
import { Hub } from '../../../src/types'
import { KafkaProducerWrapper } from '../../../src/utils/db/kafka-producer-wrapper'
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
            kafkaProducer: {
                producer: {
                    send: jest.fn(),
                } as unknown as Producer,
            } as KafkaProducerWrapper,
        }

        await runScheduledTasks(mockHubWithPluginSchedule, 'iDontExist')
        expect(mockPiscina.run).not.toHaveBeenCalled()

        await runScheduledTasks(mockHubWithPluginSchedule, 'runEveryMinute')

        expect(mockPiscina.run).toHaveBeenNthCalledWith(1, { pluginConfigId: 1, taskType: 'runEveryMinute' })
        expect(mockPiscina.run).toHaveBeenNthCalledWith(2, { pluginConfigId: 2, taskType: 'runEveryMinute' })
        expect(mockPiscina.run).toHaveBeenNthCalledWith(3, { pluginConfigId: 3, taskType: 'runEveryMinute' })

        await runScheduledTasks(mockHubWithPluginSchedule, 'runEveryHour')
        expect(mockPiscina.run).toHaveBeenNthCalledWith(4, { pluginConfigId: 4, taskType: 'runEveryHour' })
        expect(mockPiscina.run).toHaveBeenNthCalledWith(5, { pluginConfigId: 5, taskType: 'runEveryHour' })
        expect(mockPiscina.run).toHaveBeenNthCalledWith(6, { pluginConfigId: 6, taskType: 'runEveryHour' })

        await runScheduledTasks(mockHubWithPluginSchedule, 'runEveryDay')
        expect(mockPiscina.run).toHaveBeenNthCalledWith(7, { pluginConfigId: 7, taskType: 'runEveryDay' })
        expect(mockPiscina.run).toHaveBeenNthCalledWith(8, { pluginConfigId: 8, taskType: 'runEveryDay' })
        expect(mockPiscina.run).toHaveBeenNthCalledWith(9, { pluginConfigId: 9, taskType: 'runEveryDay' })
    })
})
