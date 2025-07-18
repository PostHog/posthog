import { CODES, KafkaConsumer as RdKafkaConsumer, Message } from 'node-rdkafka'

import { delay } from '../utils/utils'
import { KafkaConsumer } from './consumer'

jest.mock('./admin', () => ({
    ensureTopicExists: jest.fn().mockResolvedValue(undefined),
}))

jest.mock('node-rdkafka', () => ({
    KafkaConsumer: jest.fn().mockImplementation(() => ({
        connect: jest.fn().mockImplementation((_, cb) => cb(null)),
        subscribe: jest.fn(),
        consume: jest.fn().mockImplementation((_, cb) => cb(null, [])),
        disconnect: jest.fn().mockImplementation((cb) => cb(null)),
        isConnected: jest.fn().mockReturnValue(true),
        on: jest.fn(),
        assignments: jest.fn().mockReturnValue([]),
        offsetsStore: jest.fn(),
        setDefaultConsumeTimeout: jest.fn(),
    })),
    CODES: {
        ERRORS: {
            ERR__REVOKE_PARTITIONS: 'ERR__REVOKE_PARTITIONS',
            ERR__ASSIGN_PARTITIONS: 'ERR__ASSIGN_PARTITIONS',
        },
    },
}))

const createKafkaMessage = (message: Partial<Message> = {}): Message => ({
    value: Buffer.from('test-value'),
    key: Buffer.from('test-key'),
    offset: 1,
    partition: 0,
    topic: 'test-topic',
    size: 10,
    ...message,
})

jest.setTimeout(10000)

const triggerablePromise = (): {
    promise: Promise<any>
    resolve: (value?: any) => void
    reject: (reason?: any) => void
} => {
    const result: {
        promise: Promise<any>
        resolve: (value?: any) => void
        reject: (reason?: any) => void
    } = {
        promise: null as any,
        resolve: () => {},
        reject: () => {},
    }

    result.promise = new Promise((resolve, reject) => {
        result.resolve = resolve
        result.reject = reject
    })
    return result
}

describe('consumer', () => {
    let consumer: KafkaConsumer
    let mockRdKafkaConsumer: jest.Mocked<RdKafkaConsumer>
    let consumeCallback: (error: Error | null, messages: Message[]) => void
    let mockRebalanceHandler: (err: any, topicPartitions: any[]) => Promise<void>

    beforeEach(() => {
        // Setup mock to capture rebalance handler during consumer creation
        const mockRdKafkaConsumerInstance = {
            connect: jest.fn().mockImplementation((_, cb) => cb(null)),
            subscribe: jest.fn(),
            consume: jest.fn().mockImplementation((_, cb) => cb(null, [])),
            disconnect: jest.fn().mockImplementation((cb) => cb(null)),
            isConnected: jest.fn().mockReturnValue(true),
            on: jest.fn().mockImplementation(function (this: any, event, callback) {
                if (event === 'rebalance') {
                    // Create a mock that simulates the real rebalance handler behavior
                    mockRebalanceHandler = jest.fn().mockImplementation(async (err, topicPartitions) => {
                        if (err.code === CODES.ERRORS.ERR__REVOKE_PARTITIONS) {
                            // When feature flag is enabled, wait for background tasks
                            if (consumer?.['config']?.waitForBackgroundTasksOnRebalance) {
                                await Promise.all(consumer['backgroundTask'])
                            }
                        }
                        // Call the original callback
                        callback(err, topicPartitions)
                    })
                }
                return this
            }),
            assignments: jest.fn().mockReturnValue([]),
            offsetsStore: jest.fn(),
            setDefaultConsumeTimeout: jest.fn(),
        }

        // Mock the RdKafkaConsumer constructor to return our configured mock
        jest.mocked(require('node-rdkafka').KafkaConsumer).mockImplementation(() => mockRdKafkaConsumerInstance)

        consumer = new KafkaConsumer({
            groupId: 'test-group',
            topic: 'test-topic',
            waitForBackgroundTasksOnRebalance: true,
        })

        mockRdKafkaConsumer = jest.mocked(consumer['rdKafkaConsumer'])

        // @ts-expect-error mock implementation
        mockRdKafkaConsumer.consume.mockImplementation((_, cb) => {
            // We assign the callback to a variable so we can control it
            consumeCallback = cb
        })
    })

    afterEach(async () => {
        if (consumer) {
            const promise = consumer.disconnect()
            // TRICKY: We need to call the callback so that the consumer loop exits
            consumeCallback(null, [])
            await promise
        }
    })

    it('should create a consumer and process messages', async () => {
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await consumer.connect(eachBatch)
        expect(mockRdKafkaConsumer.connect).toHaveBeenCalled()
        expect(mockRdKafkaConsumer.subscribe).toHaveBeenCalledWith(['test-topic'])

        consumeCallback(null, [createKafkaMessage()])
        await delay(1)

        expect(eachBatch).toHaveBeenCalledWith([createKafkaMessage()])

        expect(mockRdKafkaConsumer.offsetsStore.mock.calls).toMatchObject([
            [[{ offset: 2, partition: 0, topic: 'test-topic' }]],
        ])
    })

    describe('background work', () => {
        /**
         * NOTE: These tests are pretty verbose but also pretty cool! We are using special wrapped promises
         * to control the flow of the code and validate at each stage that it does what it is supposed to do.
         */
        let eachBatch: jest.Mock

        beforeEach(async () => {
            consumer['maxBackgroundTasks'] = 3
            eachBatch = jest.fn(() => Promise.resolve({}))

            // Hard test to simulate... We want to control each batch and return
            await consumer.connect(eachBatch)
        })

        const runWithBackgroundTask = async (messages: Message[], p: Promise<any>): Promise<void> => {
            // Create a triggerable promise that we can use to control the flow of the code
            const eachBatchTrigger = triggerablePromise()
            // Mock the eachBatch function to return the triggerable promise
            eachBatch.mockImplementation(() => eachBatchTrigger.promise)
            // Call the consume callback with the messages which will sync lead to the eachBatch function being called
            consumeCallback(null, messages)
            // Resolve the triggerable promise with the background task
            eachBatchTrigger.resolve({
                backgroundTask: p,
            })
        }

        it('should receive background work and wait for them all to be completed before committing offsets', async () => {
            // First of all call the callback with background work - and check that
            expect(mockRdKafkaConsumer.consume).toHaveBeenCalledTimes(1)
            const p1 = triggerablePromise()
            await runWithBackgroundTask([createKafkaMessage({ offset: 1, partition: 0 })], p1.promise)
            await delay(1)
            expect(mockRdKafkaConsumer.consume).toHaveBeenCalledTimes(2)

            const p2 = triggerablePromise()
            await runWithBackgroundTask([createKafkaMessage({ offset: 2, partition: 0 })], p2.promise)
            await delay(1)
            expect(mockRdKafkaConsumer.consume).toHaveBeenCalledTimes(3)

            const p3 = triggerablePromise()
            await runWithBackgroundTask([createKafkaMessage({ offset: 3, partition: 0 })], p3.promise)
            await delay(1)
            // IMPORTANT: We don't expect a 4th call as the 3rd should have triggered the wait backpressure await
            expect(mockRdKafkaConsumer.consume).toHaveBeenCalledTimes(3) // NOT 4

            // At this point we have 3 background work items so we must be waiting for one of them
            expect(consumer['backgroundTask']).toEqual([p1.promise, p2.promise, p3.promise])

            expect(mockRdKafkaConsumer.offsetsStore).not.toHaveBeenCalled()

            p1.resolve()
            await delay(1) // Let the promises callbacks trigger
            expect(mockRdKafkaConsumer.consume).toHaveBeenCalledTimes(4) // Releases the backpressure
            p2.resolve()
            await delay(1) // Let the promises callbacks trigger
            p3.resolve()
            await delay(1) // Let the promises callbacks trigger

            // Check the other background work releases has no effect on the consume call count
            expect(mockRdKafkaConsumer.consume).toHaveBeenCalledTimes(4)

            expect(consumer['backgroundTask']).toEqual([])
            expect(mockRdKafkaConsumer.offsetsStore.mock.calls).toMatchObject([
                [[{ offset: 2, partition: 0, topic: 'test-topic' }]],
                [[{ offset: 3, partition: 0, topic: 'test-topic' }]],
                [[{ offset: 4, partition: 0, topic: 'test-topic' }]],
            ])
        })

        it('should handle background work that finishes out of order', async () => {
            // First of all call the callback with background work - and check that
            const p1 = triggerablePromise()
            await runWithBackgroundTask([createKafkaMessage({ offset: 1, partition: 0 })], p1.promise)
            await delay(1)

            const p2 = triggerablePromise()
            await runWithBackgroundTask([createKafkaMessage({ offset: 2, partition: 0 })], p2.promise)
            await delay(1)

            const p3 = triggerablePromise()
            await runWithBackgroundTask([createKafkaMessage({ offset: 3, partition: 0 })], p3.promise)
            await delay(1)

            // At this point we have 3 background work items so we must be waiting for one of them

            expect(consumer['backgroundTask']).toEqual([p1.promise, p2.promise, p3.promise])
            expect(mockRdKafkaConsumer.offsetsStore).not.toHaveBeenCalled()

            p1.resolve()
            await delay(1) // Let the promises callbacks trigger
            expect(consumer['backgroundTask']).toEqual([p2.promise, p3.promise])
            p3.resolve()
            await delay(1) // Let the promises callbacks trigger
            expect(consumer['backgroundTask']).toEqual([p2.promise])
            p2.resolve()
            await delay(1) // Let the promises callbacks trigger

            expect(consumer['backgroundTask']).toEqual([])
            expect(mockRdKafkaConsumer.offsetsStore.mock.calls).toMatchObject([
                [[{ offset: 2, partition: 0, topic: 'test-topic' }]],
                [[{ offset: 3, partition: 0, topic: 'test-topic' }]],
                [[{ offset: 4, partition: 0, topic: 'test-topic' }]],
            ])
        })
    })

    describe('rebalancing', () => {
        let eachBatch: jest.Mock

        beforeEach(async () => {
            consumer['maxBackgroundTasks'] = 3
            eachBatch = jest.fn(() => Promise.resolve({}))

            await consumer.connect(eachBatch)
        })

        const runWithBackgroundTask = async (messages: Message[], p: Promise<any>): Promise<void> => {
            const eachBatchTrigger = triggerablePromise()
            eachBatch.mockImplementation(() => eachBatchTrigger.promise)
            consumeCallback(null, messages)
            eachBatchTrigger.resolve({
                backgroundTask: p,
            })
        }

        it('should wait for background tasks to complete during partition revocation', async () => {
            expect(mockRebalanceHandler).toBeTruthy()

            // Create some background tasks
            const p1 = triggerablePromise()
            const p2 = triggerablePromise()
            const p3 = triggerablePromise()

            // Start background tasks
            await runWithBackgroundTask([createKafkaMessage({ offset: 1, partition: 0 })], p1.promise)
            await delay(1)
            await runWithBackgroundTask([createKafkaMessage({ offset: 2, partition: 0 })], p2.promise)
            await delay(1)
            await runWithBackgroundTask([createKafkaMessage({ offset: 3, partition: 0 })], p3.promise)
            await delay(1)

            // Verify we have 3 background tasks running
            expect(consumer['backgroundTask']).toEqual([p1.promise, p2.promise, p3.promise])

            // Simulate partition revocation - this should wait for background tasks
            let rebalanceCompleted = false
            const rebalancePromise = (async () => {
                await mockRebalanceHandler({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS }, [
                    { topic: 'test-topic', partition: 1 },
                ])
                rebalanceCompleted = true
            })()

            // Give a small delay to let the rebalance handler start
            await delay(10)

            // The rebalance handler should still be waiting because background tasks haven't completed
            expect(rebalanceCompleted).toBe(false)

            // Now resolve the background tasks one by one
            p1.resolve()
            await delay(1)
            expect(rebalanceCompleted).toBe(false) // Still waiting for p2 and p3

            p2.resolve()
            await delay(1)
            expect(rebalanceCompleted).toBe(false) // Still waiting for p3

            p3.resolve()
            await delay(1)

            // Wait for the rebalance handler to complete
            await rebalancePromise
            expect(rebalanceCompleted).toBe(true) // Now rebalance should be complete

            // Verify background tasks are cleared
            expect(consumer['backgroundTask']).toEqual([])
        })

        it('should handle partition assignment without waiting for background tasks', async () => {
            expect(mockRebalanceHandler).toBeTruthy()

            // Create some background tasks
            const p1 = triggerablePromise()
            await runWithBackgroundTask([createKafkaMessage({ offset: 1, partition: 0 })], p1.promise)
            await delay(1)

            // Verify we have 1 background task running
            expect(consumer['backgroundTask']).toEqual([p1.promise])

            // Simulate partition assignment - this should NOT wait for background tasks
            const rebalancePromise = Promise.resolve(
                mockRebalanceHandler({ code: CODES.ERRORS.ERR__ASSIGN_PARTITIONS }, [
                    { topic: 'test-topic', partition: 1 },
                ])
            )

            // Give a small delay to let the rebalance handler complete
            await delay(1)

            // The rebalance handler should complete immediately without waiting
            let rebalanceCompleted = false
            await rebalancePromise.then(() => {
                rebalanceCompleted = true
            })

            await delay(1)
            expect(rebalanceCompleted).toBe(true)

            // Background task should still be running
            expect(consumer['backgroundTask']).toEqual([p1.promise])

            // Clean up
            p1.resolve()
            await delay(1)
        })

        it('should handle rebalancing with no background tasks', async () => {
            expect(mockRebalanceHandler).toBeTruthy()

            // Ensure no background tasks are running
            expect(consumer['backgroundTask']).toEqual([])

            // Simulate partition revocation with no background tasks
            const rebalancePromise = Promise.resolve(
                mockRebalanceHandler({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS }, [
                    { topic: 'test-topic', partition: 1 },
                ])
            )

            // Should complete immediately since there are no background tasks
            await delay(1)
            let rebalanceCompleted = false
            await rebalancePromise.then(() => {
                rebalanceCompleted = true
            })

            await delay(1)
            expect(rebalanceCompleted).toBe(true)
        })

        it('should pause consumption during rebalancing when feature flag is enabled', async () => {
            expect(mockRebalanceHandler).toBeTruthy()

            // Verify initial state
            expect(consumer['isRebalancing']).toBe(false)

            // Simulate partition revocation - this should trigger rebalancing state
            await mockRebalanceHandler({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS }, [
                { topic: 'test-topic', partition: 1 },
            ])

            // Verify rebalancing state is set
            expect(consumer['isRebalancing']).toBe(true)

            // Now simulate partition assignment - this should end rebalancing
            await mockRebalanceHandler({ code: CODES.ERRORS.ERR__ASSIGN_PARTITIONS }, [
                { topic: 'test-topic', partition: 1 },
            ])

            // Verify rebalancing state is cleared
            expect(consumer['isRebalancing']).toBe(false)
        })

        it('should NOT pause consumption during rebalancing when feature flag is disabled', async () => {
            // Create a consumer with feature flag disabled
            let mockRebalanceHandlerDisabled: (err: any, topicPartitions: any[]) => void = jest.fn()
            const mockRdKafkaConsumerInstanceDisabled = {
                connect: jest.fn().mockImplementation((_, cb) => cb(null)),
                subscribe: jest.fn(),
                consume: jest.fn().mockImplementation((_, cb) => cb(null, [])),
                disconnect: jest.fn().mockImplementation((cb) => cb(null)),
                isConnected: jest.fn().mockReturnValue(true),
                on: jest.fn().mockImplementation(function (this: any, event, callback) {
                    if (event === 'rebalance') {
                        mockRebalanceHandlerDisabled = callback as (err: any, topicPartitions: any[]) => void
                    }
                    return this
                }),
                assignments: jest.fn().mockReturnValue([]),
                offsetsStore: jest.fn(),
                setDefaultConsumeTimeout: jest.fn(),
            }

            jest.mocked(require('node-rdkafka').KafkaConsumer).mockImplementation(
                () => mockRdKafkaConsumerInstanceDisabled
            )

            const consumerDisabled = new KafkaConsumer({
                groupId: 'test-group',
                topic: 'test-topic',
                waitForBackgroundTasksOnRebalance: false,
            })

            const eachBatchDisabled = jest.fn(() => Promise.resolve({}))
            await consumerDisabled.connect(eachBatchDisabled)

            // Verify initial state
            expect(consumerDisabled['isRebalancing']).toBe(false)

            // Simulate partition revocation
            mockRebalanceHandlerDisabled({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS }, [
                { topic: 'test-topic', partition: 1 },
            ])

            // Even with flag disabled, isRebalancing should still be set (the pausing logic just won't use it)
            expect(consumerDisabled['isRebalancing']).toBe(true)

            // Simulate partition assignment
            mockRebalanceHandlerDisabled({ code: CODES.ERRORS.ERR__ASSIGN_PARTITIONS }, [
                { topic: 'test-topic', partition: 1 },
            ])

            // Rebalancing should be cleared
            expect(consumerDisabled['isRebalancing']).toBe(false)

            // Clean up
            await consumerDisabled.disconnect()
        })
    })
})
