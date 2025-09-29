/* eslint-disable @typescript-eslint/require-await */
import { DateTime, Settings } from 'luxon'

import { createKafkaMessage } from '~/cdp/_tests/fixtures'
import { defaultConfig } from '~/config/config'
import { PluginsServerConfig } from '~/types'

import { CyclotronJobQueueDelay, getDelayQueue } from './job-queue-delay'

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

    describe('delay queue forwarding', () => {
        jest.useFakeTimers()
        Settings.defaultZone = 'UTC'

        let delay24h: CyclotronJobQueueDelay
        let delay60m: CyclotronJobQueueDelay
        let delay10m: CyclotronJobQueueDelay
        let produceSpy: jest.SpyInstance

        beforeEach(async () => {
            delay24h = new CyclotronJobQueueDelay(config, 'delay-24h', async () => ({
                backgroundTask: Promise.resolve(),
            }))
            delay60m = new CyclotronJobQueueDelay(config, 'delay-60m', async () => ({
                backgroundTask: Promise.resolve(),
            }))
            delay10m = new CyclotronJobQueueDelay(config, 'delay-10m', async () => ({
                backgroundTask: Promise.resolve(),
            }))

            await delay24h.startAsProducer()
            await delay60m.startAsProducer()
            await delay10m.startAsProducer()

            produceSpy = jest.spyOn(delay24h['getKafkaProducer'](), 'produce')
        })

        it('should forward job through delay queues to final destination', async () => {
            jest.setSystemTime(new Date('2025-01-01T10:00:00.000Z'))
            let mockTime = 0
            const delayMock = jest
                .spyOn(CyclotronJobQueueDelay.prototype as any, 'delayWithCancellation')
                .mockImplementation(async () => {
                    if (mockTime === 0) {
                        jest.setSystemTime(new Date('2025-01-02T10:00:00.000Z'))
                    } else if (mockTime === 1) {
                        jest.setSystemTime(new Date('2025-01-02T11:00:00.000Z'))
                    }
                    mockTime++
                    await Promise.resolve()
                })

            const getMessage = (waitMinutes: number) => {
                return {
                    key: Buffer.from('test-job-123'),
                    topic: 'cdp_cyclotron_delay-24h',
                    headers: [
                        { returnTopic: Buffer.from('hog') },
                        { queueScheduledAt: Buffer.from(DateTime.now().plus({ minutes: waitMinutes }).toISO()) },
                    ] as any,
                }
            }

            produceSpy.mockClear()

            await delay24h['consumeKafkaBatch']([
                createKafkaMessage({ data: 'delay-test' }, getMessage(1520 /* 24 hours + 80 minutes */)),
            ])
            expect(produceSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    topic: 'cdp_cyclotron_delay-60m',
                })
            )
            produceSpy.mockClear()

            await delay60m['consumeKafkaBatch']([
                createKafkaMessage({ data: 'delay-test' }, getMessage(80 /* 60 minutes + 20 minutes */)),
            ])
            expect(produceSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    topic: 'cdp_cyclotron_delay-10m',
                })
            )
            produceSpy.mockClear()

            await delay10m['consumeKafkaBatch']([
                createKafkaMessage({ data: 'delay-test' }, getMessage(20 /* 20 minutes */)),
            ])
            expect(produceSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    topic: 'cdp_cyclotron_delay-10m',
                })
            )
            produceSpy.mockClear()

            await delay10m['consumeKafkaBatch']([
                createKafkaMessage({ data: 'delay-test' }, getMessage(10 /* 10 minutes */)),
            ])
            expect(produceSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    topic: 'hog',
                })
            )
            delayMock.mockRestore()

            jest.useRealTimers()
        })
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

        beforeEach(async () => {
            await delayQueue.startAsConsumer()
            await delayQueue.startAsProducer()
            const { KafkaProducerWrapper } = require('../../../kafka/producer')
            mockProducer = await KafkaProducerWrapper.create.mock.results[0].value
        })

        it.each([
            {
                scheduledTime: () => DateTime.now().plus({ hours: 24 }),
                expectedQueue: 'delay-24h',
            },
            {
                scheduledTime: () => DateTime.now().plus({ minutes: 60 }),
                expectedQueue: 'delay-60m',
            },
            {
                scheduledTime: () => DateTime.now().plus({ minutes: 20 }),
                expectedQueue: 'delay-10m',
            },
            {
                scheduledTime: () => DateTime.now().plus({ minutes: 10 }),
                expectedQueue: 'delay-10m',
            },
            {
                scheduledTime: () => DateTime.now().minus({ minutes: 1 }),
                expectedQueue: 'delay-10m',
            },
            {
                scheduledTime: () => DateTime.now(),
                expectedQueue: 'delay-10m',
            },
            {
                scheduledTime: () => DateTime.now().minus({ minutes: 5 }),
                expectedQueue: 'delay-10m',
            },
        ])('should return $expectedQueue for scheduled time $scheduledTime', ({ scheduledTime, expectedQueue }) => {
            expect(getDelayQueue(scheduledTime())).toBe(expectedQueue)
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

/* eslint-enable @typescript-eslint/require-await */
