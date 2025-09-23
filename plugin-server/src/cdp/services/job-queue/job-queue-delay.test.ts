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
    heartbeat: jest.fn(),
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
        delayQueue = new CyclotronJobQueueDelay(config, 'delay-10m', mockConsumeBatch)

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

    describe('message routing logic', () => {
        let mockProducer: any
        let delayWithCancellationSpy: jest.SpyInstance

        beforeEach(async () => {
            await delayQueue.startAsConsumer()
            await delayQueue.startAsProducer()
            const { KafkaProducerWrapper } = require('../../../kafka/producer')
            mockProducer = await KafkaProducerWrapper.create.mock.results[0].value

            // Mock delayWithCancellation to avoid actual delays in tests
            delayWithCancellationSpy = jest
                .spyOn(delayQueue as any, 'delayWithCancellation')
                .mockResolvedValue(undefined)
        })

        afterEach(() => {
            delayWithCancellationSpy?.mockRestore()
        })

        it.each([
            {
                description: 'routes to returnTopic when scheduled time has passed',
                scheduledTime: () => DateTime.now().minus({ minutes: 1 }),
                expectedTopic: 'cdp_cyclotron_hog',
            },
            {
                description: 'routes to returnTopic when scheduled time equals current time',
                scheduledTime: () => DateTime.now(),
                expectedTopic: 'cdp_cyclotron_hog',
            },
            {
                description: 'routes back to delay queue when remaining delay exceeds maxDelayMs',
                scheduledTime: () => DateTime.now().plus({ hours: 25 }),
                expectedTopic: 'cdp_cyclotron_delay-10m',
            },
            {
                description: 'routes to returnTopic when remaining delay fits within maxDelayMs',
                scheduledTime: () => DateTime.now().plus({ minutes: 5 }),
                expectedTopic: 'cdp_cyclotron_hog',
            },
        ])('$description', async ({ scheduledTime, expectedTopic }) => {
            const returnTopic = 'cdp_cyclotron_hog'
            const mockMessage = {
                key: Buffer.from('test-key'),
                value: Buffer.from('test-value'),
                offset: 123,
                size: 100,
                topic: 'cdp_cyclotron_delay-10m',
                partition: 0,
                headers: [
                    {
                        returnTopic: Buffer.from(returnTopic),
                        queueScheduledAt: Buffer.from(scheduledTime().toISO()),
                    },
                ],
            }

            await delayQueue['consumeKafkaBatch']([mockMessage])

            expect(mockProducer.produce).toHaveBeenCalledWith({
                value: mockMessage.value,
                key: mockMessage.key,
                topic: expectedTopic,
                headers: mockMessage.headers,
            })
        })

        it.each([
            {
                description: 'missing returnTopic header',
                headers: [{ queueScheduledAt: Buffer.from(DateTime.now().toISO()) }],
            },
            {
                description: 'missing queueScheduledAt header',
                headers: [{ returnTopic: Buffer.from('hog_invocations') }],
            },
        ])('should handle $description', async ({ headers }) => {
            const mockMessage = {
                key: Buffer.from('test-key'),
                value: Buffer.from('test-value'),
                offset: 123,
                size: 100,
                topic: 'cdp_cyclotron_delay-10m',
                partition: 0,
                headers,
            }

            await delayQueue['consumeKafkaBatch']([mockMessage])

            expect(mockProducer.produce).not.toHaveBeenCalled()
            expect(mockKafkaConsumer.offsetsStore).toHaveBeenCalledWith([{ ...mockMessage, offset: 124 }])
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
                topic: 'cdp_cyclotron_delay-10m',
                partition: 0,
                headers: [
                    {
                        returnTopic: Buffer.from('delay-10m'),
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
