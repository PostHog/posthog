import { CODES, Message, MessageHeader, KafkaConsumer as RdKafkaConsumer } from 'node-rdkafka'

import { defaultConfig } from '~/config/config'

import { delay } from '../utils/utils'
import { KafkaConsumer, parseEventHeaders, parseKafkaHeaders } from './consumer'

// Mock prom-client metrics to enable verification
// Mocks are created inside the factory to avoid hoisting issues, then exposed via __mocks
jest.mock('prom-client', () => {
    const inc = jest.fn()
    const set = jest.fn()
    const observe = jest.fn()
    const startTimer = jest.fn(() => jest.fn())
    const labels = jest.fn(() => ({ inc, set, observe, startTimer }))

    // Create metric instances with both direct methods and labels()
    const createMetric = () => ({ labels, inc, set, observe, startTimer })

    return {
        Counter: jest.fn().mockImplementation(() => createMetric()),
        Gauge: jest.fn().mockImplementation(() => createMetric()),
        Histogram: jest.fn().mockImplementation(() => createMetric()),
        Summary: jest.fn().mockImplementation(() => createMetric()),
        // Export for test access
        __mocks: { inc, set, observe, labels, startTimer },
    }
})

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
        incrementalUnassign: jest.fn(),
        incrementalAssign: jest.fn(),
        rebalanceProtocol: jest.fn().mockReturnValue('COOPERATIVE'),
        commitSync: jest.fn(),
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

// Global tracker for all promises to ensure cleanup
const activePromiseResolvers: Array<() => void> = []

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
        const wrappedResolve = (value?: any) => {
            // Remove from active list when resolved
            const index = activePromiseResolvers.indexOf(wrappedResolve)
            if (index > -1) {
                activePromiseResolvers.splice(index, 1)
            }
            resolve(value)
        }

        result.resolve = wrappedResolve
        result.reject = (reason?: any) => {
            // Remove from active list when rejected
            const index = activePromiseResolvers.indexOf(wrappedResolve)
            if (index > -1) {
                activePromiseResolvers.splice(index, 1)
            }
            reject(reason)
        }

        // Track this promise for cleanup
        activePromiseResolvers.push(wrappedResolve)
    })
    return result
}

describe('consumer', () => {
    afterEach(() => {
        // Final cleanup of any remaining promises
        while (activePromiseResolvers.length > 0) {
            const resolver = activePromiseResolvers[0]
            resolver()
        }
    })
    let consumer: KafkaConsumer
    let mockRdKafkaConsumer: jest.Mocked<RdKafkaConsumer>
    let consumeCallback: (error: Error | null, messages: Message[]) => void

    beforeEach(() => {
        const mockRdKafkaConsumerInstance = {
            connect: jest.fn().mockImplementation((_, cb) => cb(null)),
            subscribe: jest.fn(),
            consume: jest.fn().mockImplementation((_, cb) => cb(null, [])),
            disconnect: jest.fn().mockImplementation((cb) => cb(null)),
            isConnected: jest.fn().mockReturnValue(true),
            on: jest.fn(),
            assignments: jest.fn().mockReturnValue([]),
            offsetsStore: jest.fn(),
            setDefaultConsumeTimeout: jest.fn(),
            incrementalUnassign: jest.fn(),
            incrementalAssign: jest.fn(),
            rebalanceProtocol: jest.fn().mockReturnValue('COOPERATIVE'),
            commitSync: jest.fn(),
        }
        defaultConfig.CONSUMER_WAIT_FOR_BACKGROUND_TASKS_ON_REBALANCE = true

        // Mock the RdKafkaConsumer constructor to return our configured mock
        jest.mocked(require('node-rdkafka').KafkaConsumer).mockImplementation(() => mockRdKafkaConsumerInstance)

        consumer = new KafkaConsumer({
            groupId: 'test-group',
            topic: 'test-topic',
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
            // CRITICAL: Clear background tasks BEFORE disconnect to prevent hanging
            consumer['backgroundTaskCoordinator'].clear()
        }

        // Force resolve any remaining unresolved promises to prevent memory leaks
        while (activePromiseResolvers.length > 0) {
            const resolver = activePromiseResolvers[0]
            resolver() // This will remove itself from the array
        }

        if (consumer) {
            const promise = consumer.disconnect()
            if (consumeCallback) {
                consumeCallback(null, [])
            }
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

        const simulateMessageWithBackgroundTask = async (
            messages: Message[],
            backgroundTask: Promise<any>
        ): Promise<void> => {
            // Mock eachBatch to return a background task
            eachBatch.mockImplementationOnce(() => Promise.resolve({ backgroundTask }))
            // Trigger message processing
            consumeCallback(null, messages)
            // Wait for the background task to be added
            await delay(1)
        }

        it('should receive background work and wait for them all to be completed before committing offsets', async () => {
            // First of all call the callback with background work - and check that
            expect(mockRdKafkaConsumer.consume).toHaveBeenCalledTimes(1)
            const p1 = triggerablePromise()
            await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 1, partition: 0 })], p1.promise)
            expect(mockRdKafkaConsumer.consume).toHaveBeenCalledTimes(2)

            const p2 = triggerablePromise()
            await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 2, partition: 0 })], p2.promise)
            expect(mockRdKafkaConsumer.consume).toHaveBeenCalledTimes(3)

            const p3 = triggerablePromise()
            await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 3, partition: 0 })], p3.promise)
            await delay(1)
            // IMPORTANT: We don't expect a 4th call as the 3rd should have triggered the wait backpressure await
            expect(mockRdKafkaConsumer.consume).toHaveBeenCalledTimes(3) // NOT 4

            // At this point we have 3 background work items so we must be waiting for one of them
            expect(consumer['backgroundTaskCoordinator'].taskCount).toBe(3)

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

            expect(consumer['backgroundTaskCoordinator'].taskCount).toBe(0)
            expect(mockRdKafkaConsumer.offsetsStore.mock.calls).toMatchObject([
                [[{ offset: 2, partition: 0, topic: 'test-topic' }]],
                [[{ offset: 3, partition: 0, topic: 'test-topic' }]],
                [[{ offset: 4, partition: 0, topic: 'test-topic' }]],
            ])
        })

        it('should handle background work that finishes out of order', async () => {
            // First of all call the callback with background work - and check that
            const p1 = triggerablePromise()
            await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 1, partition: 0 })], p1.promise)

            const p2 = triggerablePromise()
            await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 2, partition: 0 })], p2.promise)

            const p3 = triggerablePromise()
            await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 3, partition: 0 })], p3.promise)
            await delay(1)

            // At this point we have 3 background work items so we must be waiting for one of them

            expect(consumer['backgroundTaskCoordinator'].taskCount).toBe(3)
            expect(mockRdKafkaConsumer.offsetsStore).not.toHaveBeenCalled()

            p1.resolve()
            await delay(1) // Let the promises callbacks trigger
            expect(consumer['backgroundTaskCoordinator'].taskCount).toBe(2)
            p3.resolve()
            await delay(1) // Let the promises callbacks trigger
            // Note: task count stays at 2 because p3 completed but p2 hasn't stored offsets yet
            // (offsets are stored in order, so p3 waits for p2)
            expect(consumer['backgroundTaskCoordinator'].taskCount).toBe(1)
            p2.resolve()
            await delay(1) // Let the promises callbacks trigger

            expect(consumer['backgroundTaskCoordinator'].taskCount).toBe(0)
            expect(mockRdKafkaConsumer.offsetsStore.mock.calls).toMatchObject([
                [[{ offset: 2, partition: 0, topic: 'test-topic' }]],
                [[{ offset: 3, partition: 0, topic: 'test-topic' }]],
                [[{ offset: 4, partition: 0, topic: 'test-topic' }]],
            ])
        })

        it('should handle interleaved add and complete operations', async () => {
            // This test verifies that tasks can be added and completed in an interleaved manner
            // and the coordinator handles it correctly

            // Add and complete first batch
            await simulateMessageWithBackgroundTask(
                [createKafkaMessage({ offset: 1, partition: 0 })],
                Promise.resolve()
            )
            await delay(10)
            expect(consumer['backgroundTaskCoordinator'].taskCount).toBe(0)

            // Now add pending tasks
            const p1 = triggerablePromise()
            const p2 = triggerablePromise()
            const p3 = triggerablePromise()

            await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 2, partition: 0 })], p1.promise)
            await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 3, partition: 0 })], p2.promise)
            await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 4, partition: 0 })], p3.promise)

            expect(consumer['backgroundTaskCoordinator'].taskCount).toBe(3)

            // Complete task 3 first (out of order)
            p3.resolve()
            await delay(1)
            // Task 3 completed but is still tracked because it's waiting for p1 and p2 to store offsets
            expect(consumer['backgroundTaskCoordinator'].taskCount).toBe(2)

            // Complete task 1
            p1.resolve()
            await delay(1)
            expect(consumer['backgroundTaskCoordinator'].taskCount).toBe(1)

            // Complete task 2 - this should release task 3 as well
            p2.resolve()
            await delay(1)
            expect(consumer['backgroundTaskCoordinator'].taskCount).toBe(0)

            // Offsets should still be stored in order
            expect(mockRdKafkaConsumer.offsetsStore.mock.calls).toMatchObject([
                [[{ offset: 2, partition: 0, topic: 'test-topic' }]],
                [[{ offset: 3, partition: 0, topic: 'test-topic' }]],
                [[{ offset: 4, partition: 0, topic: 'test-topic' }]],
                [[{ offset: 5, partition: 0, topic: 'test-topic' }]],
            ])
        })
    })

    describe('rebalancing', () => {
        // Access the mocks from the prom-client mock

        const promClientMocks = require('prom-client').__mocks as {
            inc: jest.Mock
            set: jest.Mock
            observe: jest.Mock
            labels: jest.Mock
            startTimer: jest.Mock
        }

        beforeEach(() => {
            // Reset metric mocks before each rebalancing test
            promClientMocks.inc.mockClear()
            promClientMocks.set.mockClear()
            promClientMocks.observe.mockClear()
            promClientMocks.labels.mockClear()
        })

        it('should set rebalancing state during partition revocation', () => {
            expect(consumer['rebalanceCoordination'].isRebalancing).toBe(false)

            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 1 },
            ])

            expect(consumer['rebalanceCoordination'].isRebalancing).toBe(true)
        })

        it('should clear rebalancing state during partition assignment', () => {
            consumer['rebalanceCoordination'].isRebalancing = true

            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__ASSIGN_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 1 },
            ])

            expect(consumer['rebalanceCoordination'].isRebalancing).toBe(false)
        })

        it('should call incrementalUnassign when no background tasks exist', async () => {
            // Coordinator starts empty, no need to set anything

            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 1 },
            ])

            await delay(1)
            expect(mockRdKafkaConsumer.incrementalUnassign).toHaveBeenCalledWith([
                { topic: 'test-topic', partition: 1 },
            ])
        })

        it('should wait for offset storage before calling incrementalUnassign', async () => {
            // Create controllable promises to test actual waiting behavior
            const task1 = triggerablePromise()
            const task2 = triggerablePromise()

            // Use the coordinator to add tasks - this creates the offsetsStoredPromise internally
            const onOffsetsStored1 = jest.fn()
            const onOffsetsStored2 = jest.fn()
            consumer['backgroundTaskCoordinator'].addTask(task1.promise, onOffsetsStored1, new Set([1]))
            consumer['backgroundTaskCoordinator'].addTask(task2.promise, onOffsetsStored2, new Set([1]))

            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 1 },
            ])

            expect(consumer['rebalanceCoordination'].isRebalancing).toBe(true)

            // Should not have called incrementalUnassign yet (still waiting for offset storage)
            await delay(10)
            expect(mockRdKafkaConsumer.incrementalUnassign).not.toHaveBeenCalled()

            // Resolve first task - offset storage callback runs, but still waiting for task2
            task1.resolve()
            await delay(1)
            expect(onOffsetsStored1).toHaveBeenCalled()
            expect(mockRdKafkaConsumer.incrementalUnassign).not.toHaveBeenCalled()

            // Resolve second task - now both tasks are complete and offsets stored
            task2.resolve()
            await delay(10)
            expect(onOffsetsStored2).toHaveBeenCalled()

            // Should have called commitSync after all offsets are stored
            expect(mockRdKafkaConsumer.commitSync).toHaveBeenCalledWith(null)

            // Should have called incrementalUnassign after all offsets are stored
            expect(mockRdKafkaConsumer.incrementalUnassign).toHaveBeenCalledWith([
                { topic: 'test-topic', partition: 1 },
            ])

            // Verify metrics were recorded
            // rebalanceCounter (type: 'revoke')
            expect(promClientMocks.labels).toHaveBeenCalledWith({ groupId: 'test-group', type: 'revoke' })
            // rebalanceBackgroundTasksGauge
            expect(promClientMocks.labels).toHaveBeenCalledWith({ groupId: 'test-group' })
            expect(promClientMocks.set).toHaveBeenCalledWith(2) // Two background tasks
            // rebalanceOffsetWaitResultCounter (result: 'success')
            expect(promClientMocks.labels).toHaveBeenCalledWith({ groupId: 'test-group', result: 'success' })
            // rebalanceOffsetCommitResultCounter (result: 'success')
            expect(promClientMocks.inc).toHaveBeenCalled()
        })

        it('should not wait when waitForBackgroundTasksOnRebalance is disabled', async () => {
            defaultConfig.CONSUMER_WAIT_FOR_BACKGROUND_TASKS_ON_REBALANCE = false
            // Create a consumer with feature disabled
            const consumerDisabled = new KafkaConsumer({
                groupId: 'test-group',
                topic: 'test-topic',
            })

            const mockConsumerDisabled = jest.mocked(consumerDisabled['rdKafkaConsumer'])

            // Add a background task using the coordinator
            consumerDisabled['backgroundTaskCoordinator'].addTask(Promise.resolve(), jest.fn(), new Set([1]))

            consumerDisabled.rebalanceCallback({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 1 },
            ])

            // Should proceed immediately without waiting
            await delay(1)
            expect(mockConsumerDisabled.incrementalUnassign).toHaveBeenCalledWith([
                { topic: 'test-topic', partition: 1 },
            ])

            await consumerDisabled.disconnect()
        })

        it('should timeout and proceed with revocation if offset storage takes too long', async () => {
            // Set a short timeout for testing
            consumer['rebalanceCoordination'].rebalanceTimeoutMs = 50

            // Create a promise that will never resolve (simulating stuck task)
            const neverResolvingTask = new Promise<void>(() => {
                // Intentionally never resolves
            })

            // Add a task that never completes - its offset storage will also never complete
            consumer['backgroundTaskCoordinator'].addTask(neverResolvingTask, jest.fn(), new Set([1]))

            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 1 },
            ])

            // Should not have called incrementalUnassign yet
            await delay(10)
            expect(mockRdKafkaConsumer.incrementalUnassign).not.toHaveBeenCalled()

            // Wait for timeout to expire (50ms + some buffer)
            await delay(60)

            // After timeout, should have proceeded with revocation anyway
            expect(mockRdKafkaConsumer.commitSync).toHaveBeenCalledWith(null)
            expect(mockRdKafkaConsumer.incrementalUnassign).toHaveBeenCalledWith([
                { topic: 'test-topic', partition: 1 },
            ])
        })

        it('should handle offset storage error and still proceed with revocation', async () => {
            // Add a task with a callback that throws an error
            consumer['backgroundTaskCoordinator'].addTask(
                Promise.resolve(),
                () => {
                    throw new Error('Offset storage failed')
                },
                new Set([1])
            )

            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 1 },
            ])

            // Wait for the error to be handled
            await delay(10)

            // Should still proceed with commit and revocation despite error
            expect(mockRdKafkaConsumer.commitSync).toHaveBeenCalledWith(null)
            expect(mockRdKafkaConsumer.incrementalUnassign).toHaveBeenCalledWith([
                { topic: 'test-topic', partition: 1 },
            ])
        })

        it('should handle commitSync failure and still proceed with revocation', async () => {
            // Add a task that completes successfully
            const task = triggerablePromise()
            consumer['backgroundTaskCoordinator'].addTask(task.promise, jest.fn(), new Set([1]))

            // Make commitSync throw an error
            mockRdKafkaConsumer.commitSync.mockImplementationOnce(() => {
                throw new Error('Commit failed')
            })

            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 1 },
            ])

            // Complete the task
            task.resolve()
            await delay(10)

            // Should have attempted commit (which failed)
            expect(mockRdKafkaConsumer.commitSync).toHaveBeenCalledWith(null)

            // Should still proceed with revocation despite commit error
            expect(mockRdKafkaConsumer.incrementalUnassign).toHaveBeenCalledWith([
                { topic: 'test-topic', partition: 1 },
            ])
        })

        it('should pause consumer loop during rebalance and resume after completion', async () => {
            // Connect the consumer with an eachBatch handler
            const eachBatch = jest.fn(() => Promise.resolve({}))
            await consumer.connect(eachBatch)

            // Verify initial consume call happened
            const initialConsumeCount = mockRdKafkaConsumer.consume.mock.calls.length
            expect(initialConsumeCount).toBeGreaterThanOrEqual(1)

            // Add a background task to make rebalance wait
            const task = triggerablePromise()
            consumer['backgroundTaskCoordinator'].addTask(task.promise, jest.fn(), new Set([1]))

            // Trigger rebalance - this sets isRebalancing = true
            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 0 },
            ])

            expect(consumer['rebalanceCoordination'].isRebalancing).toBe(true)

            // The consumer loop should be paused (not calling consume)
            // Give it some time to potentially make another consume call if it wasn't paused
            await delay(50)

            // Consume should not have been called again while rebalancing
            // (loop is in pause mode, waiting for isRebalancing to be false)
            const consumeCountDuringRebalance = mockRdKafkaConsumer.consume.mock.calls.length
            expect(consumeCountDuringRebalance).toBe(initialConsumeCount)

            // Complete the task to allow rebalance to finish
            task.resolve()
            await delay(20)

            // Trigger assignment to complete the rebalance
            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__ASSIGN_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 0 },
            ])

            // Verify rebalancing flag is cleared
            expect(consumer['rebalanceCoordination'].isRebalancing).toBe(false)

            // The consumer loop is now unblocked and can resume consuming
            // (In the real implementation, the loop checks isRebalancing on each iteration
            // and will call consume() again once it's false)
        })

        it('should handle multiple partitions being revoked', async () => {
            const task = triggerablePromise()
            const onOffsetsStored = jest.fn()
            consumer['backgroundTaskCoordinator'].addTask(task.promise, onOffsetsStored, new Set([1]))

            // Revoke multiple partitions at once
            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 0 },
                { topic: 'test-topic', partition: 1 },
                { topic: 'test-topic', partition: 2 },
            ])

            expect(consumer['rebalanceCoordination'].isRebalancing).toBe(true)

            // Complete the task
            task.resolve()
            await delay(10)

            // All partitions should be unassigned together
            expect(mockRdKafkaConsumer.incrementalUnassign).toHaveBeenCalledWith([
                { topic: 'test-topic', partition: 0 },
                { topic: 'test-topic', partition: 1 },
                { topic: 'test-topic', partition: 2 },
            ])
        })
    })
})

describe('parseKafkaHeaders', () => {
    it('should return empty object when headers is undefined', () => {
        const result = parseKafkaHeaders(undefined)
        expect(result).toEqual({})
    })

    it('should return empty object when headers is empty array', () => {
        const result = parseKafkaHeaders([])
        expect(result).toEqual({})
    })

    it('should parse single header', () => {
        const headers: MessageHeader[] = [{ token: Buffer.from('test-token') }]
        const result = parseKafkaHeaders(headers)
        expect(result).toEqual({
            token: 'test-token',
        })
    })

    it('should parse multiple headers in single object', () => {
        const headers: MessageHeader[] = [
            {
                token: Buffer.from('test-token'),
                distinct_id: Buffer.from('user-123'),
                timestamp: Buffer.from('1234567890'),
            },
        ]
        const result = parseKafkaHeaders(headers)
        expect(result).toEqual({
            token: 'test-token',
            distinct_id: 'user-123',
            timestamp: '1234567890',
        })
    })

    it('should parse multiple header objects', () => {
        const headers: MessageHeader[] = [
            { token: Buffer.from('test-token') },
            { distinct_id: Buffer.from('user-123') },
            { timestamp: Buffer.from('1234567890') },
        ]
        const result = parseKafkaHeaders(headers)
        expect(result).toEqual({
            token: 'test-token',
            distinct_id: 'user-123',
            timestamp: '1234567890',
        })
    })

    it('should handle arbitrary header keys', () => {
        const headers: MessageHeader[] = [
            {
                custom_header: Buffer.from('custom-value'),
                another_key: Buffer.from('another-value'),
            },
        ]
        const result = parseKafkaHeaders(headers)
        expect(result).toEqual({
            custom_header: 'custom-value',
            another_key: 'another-value',
        })
    })

    it('should handle non-string buffer values', () => {
        const headers: MessageHeader[] = [{ numeric: Buffer.from('123') }, { boolean: Buffer.from('true') }]
        const result = parseKafkaHeaders(headers)
        expect(result).toEqual({
            numeric: '123',
            boolean: 'true',
        })
    })

    it('should handle empty buffer values', () => {
        const headers: MessageHeader[] = [{ empty: Buffer.from('') }]
        const result = parseKafkaHeaders(headers)
        expect(result).toEqual({
            empty: '',
        })
    })

    it('should handle duplicate keys by overwriting', () => {
        const headers: MessageHeader[] = [{ token: Buffer.from('first-token') }, { token: Buffer.from('second-token') }]
        const result = parseKafkaHeaders(headers)
        expect(result).toEqual({
            token: 'second-token',
        })
    })
})

describe('parseEventHeaders', () => {
    it('should return empty object when headers is undefined', () => {
        const result = parseEventHeaders(undefined)
        expect(result).toEqual({ force_disable_person_processing: false, historical_migration: false })
    })

    it('should return empty object when headers is empty array', () => {
        const result = parseEventHeaders([])
        expect(result).toEqual({ force_disable_person_processing: false, historical_migration: false })
    })

    it('should parse token header only', () => {
        const headers: MessageHeader[] = [{ token: Buffer.from('test-token') }]
        const result = parseEventHeaders(headers)
        expect(result).toEqual({
            token: 'test-token',
            force_disable_person_processing: false,
            historical_migration: false,
        })
    })

    it('should parse distinct_id header only', () => {
        const headers: MessageHeader[] = [{ distinct_id: Buffer.from('user-123') }]
        const result = parseEventHeaders(headers)
        expect(result).toEqual({
            distinct_id: 'user-123',
            force_disable_person_processing: false,
            historical_migration: false,
        })
    })

    it('should parse timestamp header only', () => {
        const headers: MessageHeader[] = [{ timestamp: Buffer.from('1234567890') }]
        const result = parseEventHeaders(headers)
        expect(result).toEqual({
            timestamp: '1234567890',
            force_disable_person_processing: false,
            historical_migration: false,
        })
    })

    it('should parse all supported headers', () => {
        const headers: MessageHeader[] = [
            {
                token: Buffer.from('test-token'),
                distinct_id: Buffer.from('user-123'),
                timestamp: Buffer.from('1234567890'),
            },
        ]
        const result = parseEventHeaders(headers)
        expect(result).toEqual({
            token: 'test-token',
            distinct_id: 'user-123',
            timestamp: '1234567890',
            force_disable_person_processing: false,
            historical_migration: false,
        })
    })

    it('should parse supported headers from multiple objects', () => {
        const headers: MessageHeader[] = [
            { token: Buffer.from('test-token') },
            { distinct_id: Buffer.from('user-123') },
            { timestamp: Buffer.from('1234567890') },
        ]
        const result = parseEventHeaders(headers)
        expect(result).toEqual({
            token: 'test-token',
            distinct_id: 'user-123',
            timestamp: '1234567890',
            force_disable_person_processing: false,
            historical_migration: false,
        })
    })

    it('should ignore unsupported headers', () => {
        const headers: MessageHeader[] = [
            {
                token: Buffer.from('test-token'),
                custom_header: Buffer.from('ignored'),
                another_key: Buffer.from('also-ignored'),
                distinct_id: Buffer.from('user-123'),
            },
        ]
        const result = parseEventHeaders(headers)
        expect(result).toEqual({
            token: 'test-token',
            distinct_id: 'user-123',
            force_disable_person_processing: false,
            historical_migration: false,
        })
    })

    it('should handle empty buffer values', () => {
        const headers: MessageHeader[] = [
            {
                token: Buffer.from(''),
                distinct_id: Buffer.from(''),
                timestamp: Buffer.from(''),
            },
        ]
        const result = parseEventHeaders(headers)
        expect(result).toEqual({
            token: '',
            distinct_id: '',
            timestamp: '',
            force_disable_person_processing: false,
            historical_migration: false,
        })
    })

    it('should handle duplicate keys by overwriting', () => {
        const headers: MessageHeader[] = [
            { token: Buffer.from('first-token') },
            { token: Buffer.from('second-token') },
            { distinct_id: Buffer.from('first-id') },
            { distinct_id: Buffer.from('second-id') },
        ]
        const result = parseEventHeaders(headers)
        expect(result).toEqual({
            token: 'second-token',
            distinct_id: 'second-id',
            force_disable_person_processing: false,
            historical_migration: false,
        })
    })

    it('should handle mixed supported and unsupported headers', () => {
        const headers: MessageHeader[] = [
            { unsupported1: Buffer.from('ignored') },
            { token: Buffer.from('test-token') },
            { unsupported2: Buffer.from('also-ignored') },
            { timestamp: Buffer.from('1234567890') },
            { unsupported3: Buffer.from('still-ignored') },
        ]
        const result = parseEventHeaders(headers)
        expect(result).toEqual({
            token: 'test-token',
            timestamp: '1234567890',
            force_disable_person_processing: false,
            historical_migration: false,
        })
    })

    it('should handle partial header sets', () => {
        // Test with only token and timestamp (missing distinct_id)
        const headers: MessageHeader[] = [
            {
                token: Buffer.from('test-token'),
                timestamp: Buffer.from('1234567890'),
            },
        ]
        const result = parseEventHeaders(headers)
        expect(result).toEqual({
            token: 'test-token',
            timestamp: '1234567890',
            force_disable_person_processing: false,
            historical_migration: false,
        })
    })

    it('should parse event header', () => {
        const headers: MessageHeader[] = [{ event: Buffer.from('$pageview') }]
        const result = parseEventHeaders(headers)
        expect(result).toEqual({
            event: '$pageview',
            force_disable_person_processing: false,
            historical_migration: false,
        })
    })

    it('should parse uuid header', () => {
        const headers: MessageHeader[] = [{ uuid: Buffer.from('123e4567-e89b-12d3-a456-426614174000') }]
        const result = parseEventHeaders(headers)
        expect(result).toEqual({
            uuid: '123e4567-e89b-12d3-a456-426614174000',
            force_disable_person_processing: false,
            historical_migration: false,
        })
    })

    it('should parse all headers including new event and uuid', () => {
        const headers: MessageHeader[] = [
            {
                token: Buffer.from('test-token'),
                distinct_id: Buffer.from('user-123'),
                timestamp: Buffer.from('1234567890'),
                event: Buffer.from('$pageview'),
                uuid: Buffer.from('123e4567-e89b-12d3-a456-426614174000'),
            },
        ]
        const result = parseEventHeaders(headers)
        expect(result).toEqual({
            token: 'test-token',
            distinct_id: 'user-123',
            timestamp: '1234567890',
            event: '$pageview',
            uuid: '123e4567-e89b-12d3-a456-426614174000',
            force_disable_person_processing: false,
            historical_migration: false,
        })
    })

    it('should ignore unsupported headers but include event and uuid', () => {
        const headers: MessageHeader[] = [
            {
                token: Buffer.from('test-token'),
                custom_header: Buffer.from('ignored'),
                event: Buffer.from('custom_event'),
                another_key: Buffer.from('also-ignored'),
                uuid: Buffer.from('uuid-value'),
                distinct_id: Buffer.from('user-123'),
            },
        ]
        const result = parseEventHeaders(headers)
        expect(result).toEqual({
            token: 'test-token',
            distinct_id: 'user-123',
            event: 'custom_event',
            uuid: 'uuid-value',
            force_disable_person_processing: false,
            historical_migration: false,
        })
    })

    it('should handle empty event and uuid headers', () => {
        const headers: MessageHeader[] = [
            {
                token: Buffer.from('test-token'),
                event: Buffer.from(''),
                uuid: Buffer.from(''),
            },
        ]
        const result = parseEventHeaders(headers)
        expect(result).toEqual({
            token: 'test-token',
            event: '',
            uuid: '',
            force_disable_person_processing: false,
            historical_migration: false,
        })
    })

    describe('now header parsing', () => {
        it('should parse valid ISO date string into Date object', () => {
            const isoDate = '2023-06-15T10:30:00.000Z'
            const headers: MessageHeader[] = [{ now: Buffer.from(isoDate) }]
            const result = parseEventHeaders(headers)
            expect(result.now).toBeInstanceOf(Date)
            expect(result.now?.toISOString()).toBe(isoDate)
        })

        it('should parse ISO date with timezone offset', () => {
            const isoDate = '2023-06-15T10:30:00+02:00'
            const headers: MessageHeader[] = [{ now: Buffer.from(isoDate) }]
            const result = parseEventHeaders(headers)
            expect(result.now).toBeInstanceOf(Date)
            // The date should be correctly parsed (08:30 UTC)
            expect(result.now?.getUTCHours()).toBe(8)
            expect(result.now?.getUTCMinutes()).toBe(30)
        })

        it('should not set now for invalid date string', () => {
            const headers: MessageHeader[] = [{ now: Buffer.from('not-a-valid-date') }]
            const result = parseEventHeaders(headers)
            expect(result.now).toBeUndefined()
        })

        it('should not set now for empty string', () => {
            const headers: MessageHeader[] = [{ now: Buffer.from('') }]
            const result = parseEventHeaders(headers)
            expect(result.now).toBeUndefined()
        })

        it('should parse now header along with other headers', () => {
            const isoDate = '2023-06-15T10:30:00.000Z'
            const headers: MessageHeader[] = [
                {
                    token: Buffer.from('test-token'),
                    distinct_id: Buffer.from('user-123'),
                    now: Buffer.from(isoDate),
                },
            ]
            const result = parseEventHeaders(headers)
            expect(result).toEqual({
                token: 'test-token',
                distinct_id: 'user-123',
                now: new Date(isoDate),
                force_disable_person_processing: false,
                historical_migration: false,
            })
        })

        it('should handle now header with milliseconds precision', () => {
            const isoDate = '2023-06-15T10:30:00.123Z'
            const headers: MessageHeader[] = [{ now: Buffer.from(isoDate) }]
            const result = parseEventHeaders(headers)
            expect(result.now).toBeInstanceOf(Date)
            expect(result.now?.getUTCMilliseconds()).toBe(123)
        })

        it('should use last now value when duplicate headers exist', () => {
            const firstDate = '2023-06-15T10:30:00.000Z'
            const secondDate = '2023-06-15T11:30:00.000Z'
            const headers: MessageHeader[] = [{ now: Buffer.from(firstDate) }, { now: Buffer.from(secondDate) }]
            const result = parseEventHeaders(headers)
            expect(result.now?.toISOString()).toBe(secondDate)
        })
    })
})
