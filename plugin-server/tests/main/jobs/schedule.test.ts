import { KAFKA_SCHEDULED_TASKS } from '../../../src/config/kafka-topics'
import { KafkaProducerWrapper } from '../../../src/kafka/producer'
import { runScheduledTasks } from '../../../src/main/graphile-worker/schedule'
import { Hub } from '../../../src/types'
import { UUID } from '../../../src/utils/utils'

const mockHub: Hub = {
    instanceId: new UUID('F8B2F832-6639-4596-ABFC-F9664BC88E84'),
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
                queueMessages: jest.fn(() => Promise.resolve()),
            } as unknown as KafkaProducerWrapper,
            USE_KAFKA_FOR_SCHEDULED_TASKS: true,
        }

        await runScheduledTasks(mockHubWithPluginSchedule, mockPiscina as any, 'runEveryMinute', {
            job: { run_at: new Date() },
        } as any)

        expect(mockHubWithPluginSchedule.kafkaProducer.queueMessages).toHaveBeenNthCalledWith(1, {
            kafkaMessage: {
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
            },
        })
        expect(mockHubWithPluginSchedule.kafkaProducer.queueMessages).toHaveBeenNthCalledWith(2, {
            kafkaMessage: {
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
            },
        })
        expect(mockHubWithPluginSchedule.kafkaProducer.queueMessages).toHaveBeenNthCalledWith(3, {
            kafkaMessage: {
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
            },
        })

        await runScheduledTasks(mockHubWithPluginSchedule, mockPiscina as any, 'runEveryHour', {
            job: { run_at: new Date() },
        } as any)
        expect(mockHubWithPluginSchedule.kafkaProducer.queueMessages).toHaveBeenNthCalledWith(4, {
            kafkaMessage: {
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
            },
        })
        expect(mockHubWithPluginSchedule.kafkaProducer.queueMessages).toHaveBeenNthCalledWith(5, {
            kafkaMessage: {
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
            },
        })
        expect(mockHubWithPluginSchedule.kafkaProducer.queueMessages).toHaveBeenNthCalledWith(6, {
            kafkaMessage: {
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
            },
        })

        await runScheduledTasks(mockHubWithPluginSchedule, mockPiscina as any, 'runEveryDay', {
            job: { run_at: new Date() },
        } as any)
        expect(mockHubWithPluginSchedule.kafkaProducer.queueMessages).toHaveBeenNthCalledWith(7, {
            kafkaMessage: {
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
            },
        })
        expect(mockHubWithPluginSchedule.kafkaProducer.queueMessages).toHaveBeenNthCalledWith(8, {
            kafkaMessage: {
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
            },
        })
        expect(mockHubWithPluginSchedule.kafkaProducer.queueMessages).toHaveBeenNthCalledWith(9, {
            kafkaMessage: {
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
            },
        })
    })
})
