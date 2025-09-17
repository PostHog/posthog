import { DateTime } from 'luxon'

import { defaultConfig } from '~/config/config'
import { PluginsServerConfig } from '~/types'

import { CyclotronJobQueueDelay } from './job-queue-delay'

const mockKafkaConsumer = {
    isHealthy: jest.fn().mockReturnValue(true),
    isShuttingDown: jest.fn().mockReturnValue(false),
    isRebalancing: jest.fn().mockReturnValue(false),
    offsetsStore: jest.fn(),
    disconnect: jest.fn(),
    connect: jest.fn().mockResolvedValue(undefined),
}

jest.mock('../../../kafka/consumer', () => ({
    KafkaConsumer: jest.fn().mockImplementation(() => mockKafkaConsumer),
}))

jest.mock('../../../kafka/producer', () => ({
    KafkaProducerWrapper: {
        create: jest.fn().mockResolvedValue({
            produce: jest.fn(),
            disconnect: jest.fn(),
        }),
    },
}))

describe('CyclotronJobQueueDelay', () => {
    let config: PluginsServerConfig
    let mockConsumeBatch: jest.Mock
    let delayQueue: CyclotronJobQueueDelay

    beforeEach(() => {
        config = { ...defaultConfig }
        mockConsumeBatch = jest.fn().mockResolvedValue({ backgroundTask: Promise.resolve() })
        delayQueue = new CyclotronJobQueueDelay(config, 'delay_10m', mockConsumeBatch)

        jest.clearAllMocks()

        mockKafkaConsumer.isShuttingDown.mockReturnValue(false)
        mockKafkaConsumer.isRebalancing.mockReturnValue(false)
    })

    describe('delayWithCancellation', () => {
        it('should complete delay normally when no cancellation', async () => {
            await delayQueue.startAsConsumer()

            const startTime = Date.now()
            await delayQueue['delayWithCancellation'](100)
            const endTime = Date.now()

            expect(endTime - startTime).toBeGreaterThanOrEqual(90)
            expect(endTime - startTime).toBeLessThan(200)
        })

        it('should cancel delay when consumer is shutting down', async () => {
            await delayQueue.startAsConsumer()

            const delayPromise = delayQueue['delayWithCancellation'](5000)

            setTimeout(() => {
                mockKafkaConsumer.isShuttingDown.mockReturnValue(true)
            }, 100)

            await expect(delayPromise).rejects.toThrow('Delay cancelled due to consumer shutdown or rebalancing')
        })

        it('should cancel delay when consumer is rebalancing', async () => {
            await delayQueue.startAsConsumer()

            const delayPromise = delayQueue['delayWithCancellation'](5000)

            setTimeout(() => {
                mockKafkaConsumer.isRebalancing.mockReturnValue(true)
            }, 100)

            await expect(delayPromise).rejects.toThrow('Delay cancelled due to consumer shutdown or rebalancing')
        })
    })

    describe('consumeKafkaBatch with cancellation', () => {
        it('should throw cancellation errors during delay processing', async () => {
            await delayQueue.startAsConsumer()
            await delayQueue.startAsProducer()

            const mockMessage = {
                key: Buffer.from('test-key'),
                value: Buffer.from('test-value'),
                offset: 123,
                size: 100,
                topic: 'cdp_cyclotron_delay_10m',
                partition: 0,
                headers: [
                    {
                        returnTopic: Buffer.from('delay_10m'),
                        queueScheduledAt: Buffer.from(DateTime.now().plus({ minutes: 1 }).toISO()),
                    },
                ],
            }

            const processPromise = delayQueue['consumeKafkaBatch']([mockMessage])

            setTimeout(() => {
                mockKafkaConsumer.isShuttingDown.mockReturnValue(true)
            }, 100)

            await expect(processPromise).rejects.toThrow('Delay cancelled due to consumer shutdown or rebalancing')
        })
    })
})
