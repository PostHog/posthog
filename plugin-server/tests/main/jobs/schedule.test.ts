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
        expect(mockHubWithPluginSchedule.kafkaProducer.producer.send).not.toHaveBeenCalled()

        await runScheduledTasks(mockHubWithPluginSchedule, 'runEveryMinute')

        expect(mockHubWithPluginSchedule.kafkaProducer.producer.send).toHaveBeenNthCalledWith(1, {
            topic: KAFKA_SCHEDULED_TASKS,
            messages: [
                {
                    key: '1',
                    value: JSON.stringify({
                        pluginConfigId: 1,
                        taskType: 'runEveryMinute',
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
                        pluginConfigId: 2,
                        taskType: 'runEveryMinute',
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
                        pluginConfigId: 3,
                        taskType: 'runEveryMinute',
                    }),
                },
            ],
        })

        await runScheduledTasks(mockHubWithPluginSchedule, 'runEveryHour')
        expect(mockHubWithPluginSchedule.kafkaProducer.producer.send).toHaveBeenNthCalledWith(4, {
            topic: KAFKA_SCHEDULED_TASKS,
            messages: [
                {
                    key: '4',
                    value: JSON.stringify({
                        pluginConfigId: 4,
                        taskType: 'runEveryHour',
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
                        pluginConfigId: 5,
                        taskType: 'runEveryHour',
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
                        pluginConfigId: 6,
                        taskType: 'runEveryHour',
                    }),
                },
            ],
        })

        await runScheduledTasks(mockHubWithPluginSchedule, 'runEveryDay')
        expect(mockHubWithPluginSchedule.kafkaProducer.producer.send).toHaveBeenNthCalledWith(7, {
            topic: KAFKA_SCHEDULED_TASKS,
            messages: [
                {
                    key: '7',
                    value: JSON.stringify({
                        pluginConfigId: 7,
                        taskType: 'runEveryDay',
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
                        pluginConfigId: 8,
                        taskType: 'runEveryDay',
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
                        pluginConfigId: 9,
                        taskType: 'runEveryDay',
                    }),
                },
            ],
        })
    })
})
