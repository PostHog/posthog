import { Producer } from 'kafkajs'

import { KAFKA_SCHEDULED_TASKS } from '../../../src/config/kafka-topics'
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
            USE_KAFKA_FOR_SCHEDULED_TASKS: true,
        }

        await runScheduledTasks(mockHubWithPluginSchedule, mockPiscina as any, 'runEveryMinute', {
            job: { run_at: new Date() },
        } as any)

        expect(mockHubWithPluginSchedule.kafkaProducer.producer.send).toHaveBeenNthCalledWith(1, {
            topic: KAFKA_SCHEDULED_TASKS,
            messages: [
                {
                    key: '1',
                    value: JSON.stringify({
                        taskType: 'runEveryMinute',
                        pluginConfigId: 1,
                    }),
                },
            ],
        })
        expect(mockHubWithPluginSchedule.kafkaProducer.producer.send).toHaveBeenNthCalledWith(2, {
            topic: KAFKA_SCHEDULED_TASKS,
            messages: [
                {
                    key: '2',
                    value: JSON.stringify({
                        taskType: 'runEveryMinute',
                        pluginConfigId: 2,
                    }),
                },
            ],
        })
        expect(mockHubWithPluginSchedule.kafkaProducer.producer.send).toHaveBeenNthCalledWith(3, {
            topic: KAFKA_SCHEDULED_TASKS,
            messages: [
                {
                    key: '3',
                    value: JSON.stringify({
                        taskType: 'runEveryMinute',
                        pluginConfigId: 3,
                    }),
                },
            ],
        })

        await runScheduledTasks(mockHubWithPluginSchedule, mockPiscina as any, 'runEveryHour', {
            job: { run_at: new Date() },
        } as any)
        expect(mockHubWithPluginSchedule.kafkaProducer.producer.send).toHaveBeenNthCalledWith(4, {
            topic: KAFKA_SCHEDULED_TASKS,
            messages: [
                {
                    key: '4',
                    value: JSON.stringify({
                        taskType: 'runEveryHour',
                        pluginConfigId: 4,
                    }),
                },
            ],
        })
        expect(mockHubWithPluginSchedule.kafkaProducer.producer.send).toHaveBeenNthCalledWith(5, {
            topic: KAFKA_SCHEDULED_TASKS,
            messages: [
                {
                    key: '5',
                    value: JSON.stringify({
                        taskType: 'runEveryHour',
                        pluginConfigId: 5,
                    }),
                },
            ],
        })
        expect(mockHubWithPluginSchedule.kafkaProducer.producer.send).toHaveBeenNthCalledWith(6, {
            topic: KAFKA_SCHEDULED_TASKS,
            messages: [
                {
                    key: '6',
                    value: JSON.stringify({
                        taskType: 'runEveryHour',
                        pluginConfigId: 6,
                    }),
                },
            ],
        })

        await runScheduledTasks(mockHubWithPluginSchedule, mockPiscina as any, 'runEveryDay', {
            job: { run_at: new Date() },
        } as any)
        expect(mockHubWithPluginSchedule.kafkaProducer.producer.send).toHaveBeenNthCalledWith(7, {
            topic: KAFKA_SCHEDULED_TASKS,
            messages: [
                {
                    key: '7',
                    value: JSON.stringify({
                        taskType: 'runEveryDay',
                        pluginConfigId: 7,
                    }),
                },
            ],
        })
        expect(mockHubWithPluginSchedule.kafkaProducer.producer.send).toHaveBeenNthCalledWith(8, {
            topic: KAFKA_SCHEDULED_TASKS,
            messages: [
                {
                    key: '8',
                    value: JSON.stringify({
                        taskType: 'runEveryDay',
                        pluginConfigId: 8,
                    }),
                },
            ],
        })
        expect(mockHubWithPluginSchedule.kafkaProducer.producer.send).toHaveBeenNthCalledWith(9, {
            topic: KAFKA_SCHEDULED_TASKS,
            messages: [
                {
                    key: '9',
                    value: JSON.stringify({
                        taskType: 'runEveryDay',
                        pluginConfigId: 9,
                    }),
                },
            ],
        })
    })
})
