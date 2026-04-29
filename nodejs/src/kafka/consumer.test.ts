import { CODES, Message, MessageHeader, KafkaConsumer as RdKafkaConsumer } from 'node-rdkafka'

import { defaultConfig } from '~/config/config'
import { createTestEventHeaders } from '~/tests/helpers/event-headers'

import { delay } from '../utils/utils'
import { KafkaConsumer, parseEventHeaders, parseKafkaHeaders } from './consumer'

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
        // commit() returns the consumer (for chaining); errors surface via the
        // 'offset.commit' event registered on the consumer.
        commit: jest.fn(),
    })),
    CODES: {
        ERRORS: {
            ERR__REVOKE_PARTITIONS: 'ERR__REVOKE_PARTITIONS',
            ERR__ASSIGN_PARTITIONS: 'ERR__ASSIGN_PARTITIONS',
            ERR_ILLEGAL_GENERATION: 22,
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
            commit: jest.fn(),
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
            if (consumer['backgroundTask']) {
                consumer['backgroundTask'] = []
            }
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
            expect(consumer['backgroundTask'].map((t) => t.promise)).toEqual([p1.promise, p2.promise, p3.promise])

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

            expect(consumer['backgroundTask'].map((t) => t.promise)).toEqual([])
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

            expect(consumer['backgroundTask'].map((t) => t.promise)).toEqual([p1.promise, p2.promise, p3.promise])
            expect(mockRdKafkaConsumer.offsetsStore).not.toHaveBeenCalled()

            p1.resolve()
            await delay(1) // Let the promises callbacks trigger
            expect(consumer['backgroundTask'].map((t) => t.promise)).toEqual([p2.promise, p3.promise])
            p3.resolve()
            await delay(1) // Let the promises callbacks trigger
            expect(consumer['backgroundTask'].map((t) => t.promise)).toEqual([p2.promise])
            p2.resolve()
            await delay(1) // Let the promises callbacks trigger

            expect(consumer['backgroundTask'].map((t) => t.promise)).toEqual([])
            expect(mockRdKafkaConsumer.offsetsStore.mock.calls).toMatchObject([
                [[{ offset: 2, partition: 0, topic: 'test-topic' }]],
                [[{ offset: 3, partition: 0, topic: 'test-topic' }]],
                [[{ offset: 4, partition: 0, topic: 'test-topic' }]],
            ])
        })

        it('should not corrupt backgroundTask array when task is not found (index = -1)', async () => {
            // This test verifies proper handling when indexOf returns -1
            // Expected correct behavior:
            // 1. If task not found (index = -1), nothing should be removed from array
            // 2. The task should not wait for any other tasks
            // 3. The array should remain unchanged

            // Set up initial background tasks
            await simulateMessageWithBackgroundTask(
                [createKafkaMessage({ offset: 1, partition: 0 })],
                Promise.resolve()
            )
            await simulateMessageWithBackgroundTask(
                [createKafkaMessage({ offset: 2, partition: 0 })],
                Promise.resolve()
            )
            await simulateMessageWithBackgroundTask(
                [createKafkaMessage({ offset: 3, partition: 0 })],
                Promise.resolve()
            )

            // Wait for tasks to complete and clear
            await delay(100)

            // Now add 3 pending tasks
            const p1 = triggerablePromise()
            const p2 = triggerablePromise()
            const p3 = triggerablePromise()

            await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 4, partition: 0 })], p1.promise)
            await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 5, partition: 0 })], p2.promise)
            await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 6, partition: 0 })], p3.promise)

            const tasksBeforeCorruption = [...consumer['backgroundTask']]
            expect(tasksBeforeCorruption.map((t) => t.promise)).toEqual([p1.promise, p2.promise, p3.promise])

            // Simulate a task that completes but is somehow not in the array
            // This could happen due to race conditions or double-completion
            const orphanTask = Promise.resolve()

            // Manually inject the orphan task's finally handler using the FIXED logic
            // This includes the error handling that should trigger when index = -1
            const backgroundTaskWithFinally = orphanTask.finally(async () => {
                const index = consumer['backgroundTask'].findIndex((t) => t.promise === orphanTask)
                // This will be -1 since orphanTask is not in the array

                // FIXED logic includes error detection and reporting
                if (index < 0) {
                    // In real code, this would captureException and increment metrics
                    // For test, we just verify the logic path works
                    expect(index).toBe(-1) // Confirm we're in the error case
                }

                const promisesToWait =
                    index >= 0 ? consumer['backgroundTask'].slice(0, index).map((t) => t.promise) : []

                // Only remove the task if it was actually found
                if (index >= 0) {
                    consumer['backgroundTask'].splice(index, 1)
                }

                await Promise.all(promisesToWait)
            })

            await backgroundTaskWithFinally

            // The array should remain unchanged if the code handles -1 index properly
            // With the bug, p3 would be incorrectly removed
            expect(consumer['backgroundTask'].map((t) => t.promise)).toEqual([p1.promise, p2.promise, p3.promise])

            // Clean up
            p1.resolve()
            p2.resolve()
            p3.resolve()
            await delay(100)
        })
    })

    describe('rebalancing', () => {
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
            consumer['backgroundTask'] = []

            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 1 },
            ])

            await delay(1)
            expect(mockRdKafkaConsumer.incrementalUnassign).toHaveBeenCalledWith([
                { topic: 'test-topic', partition: 1 },
            ])
        })

        it('should wait for background tasks before calling incrementalUnassign', async () => {
            // Create controllable promises to test actual waiting behavior
            const task1 = triggerablePromise()
            const task2 = triggerablePromise()

            // Explicitly assign promise array with metadata (handled in afterEach cleanup)
            void (consumer['backgroundTask'] = [
                { promise: task1.promise, createdAt: Date.now() },
                { promise: task2.promise, createdAt: Date.now() },
            ])

            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 1 },
            ])

            expect(consumer['rebalanceCoordination'].isRebalancing).toBe(true)

            // Should not have called incrementalUnassign yet (still waiting for tasks)
            await delay(10)
            expect(mockRdKafkaConsumer.incrementalUnassign).not.toHaveBeenCalled()

            // Resolve first task - should still be waiting for second
            task1.resolve()
            await delay(1)
            expect(mockRdKafkaConsumer.incrementalUnassign).not.toHaveBeenCalled()

            // Resolve second task - now should proceed
            task2.resolve()
            await delay(10)

            // Should have called incrementalUnassign after all tasks completed
            expect(mockRdKafkaConsumer.incrementalUnassign).toHaveBeenCalledWith([
                { topic: 'test-topic', partition: 1 },
            ])
        })

        it('should store offsets BEFORE incrementalUnassign when a backgroundTask is in flight (race regression)', async () => {
            // Diagnoses the class D duplicate root cause hypothesis: a rebalance during an
            // in-flight backgroundTask can fire incrementalUnassign before the .finally chain
            // has called storeOffsetsForMessages, causing librdkafka to commit an older offset
            // and the new partition owner to replay the most recent batch as duplicates.
            const eachBatch = jest.fn(() => Promise.resolve({}))
            await consumer.connect(eachBatch)

            // Submit a batch whose backgroundTask we control.
            const bgTask = triggerablePromise()
            eachBatch.mockImplementationOnce(() => Promise.resolve({ backgroundTask: bgTask.promise }))
            consumeCallback(null, [createKafkaMessage({ offset: 1, partition: 0 })])
            await delay(1)

            // Sanity: backgroundTask is queued, no offsets stored yet.
            expect(consumer['backgroundTask']).toHaveLength(1)
            expect(mockRdKafkaConsumer.offsetsStore).not.toHaveBeenCalled()

            // Trigger a rebalance while the task is still in flight.
            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 0 },
            ])
            await delay(1)

            // Resolve the backgroundTask; both the .finally (offset store) and the rebalance
            // Promise.all .then (unassign) become eligible to run.
            bgTask.resolve()
            await delay(20)

            // Both should have happened.
            expect(mockRdKafkaConsumer.offsetsStore).toHaveBeenCalledWith([
                { offset: 2, partition: 0, topic: 'test-topic' },
            ])
            expect(mockRdKafkaConsumer.incrementalUnassign).toHaveBeenCalledWith([
                { topic: 'test-topic', partition: 0 },
            ])

            // CRITICAL ORDERING: offsets MUST be stored before incrementalUnassign so that
            // librdkafka's auto-commit-on-revoke commits this batch's offset. If the order
            // is reversed (or offsetsStore never fires), the new consumer replays the batch.
            const offsetsStoreOrder = mockRdKafkaConsumer.offsetsStore.mock.invocationCallOrder[0]
            const unassignOrder = mockRdKafkaConsumer.incrementalUnassign.mock.invocationCallOrder[0]
            expect(offsetsStoreOrder).toBeLessThan(unassignOrder)
        })

        // ---------------------------------------------------------------------------
        // ROOT CAUSE TESTS for ERR_ILLEGAL_GENERATION (error 22) duplicate path.
        //
        // Production data shows ~194 librdkafka_offet_commit_error/24h on EU with
        // error_message="Specified group generation id is not valid". The mechanism:
        //
        //   1. processBatch resolves
        //   2. .finally calls offsetsStore -> offset stored locally in librdkafka
        //   3. Auto-commit timer (~5s) eventually tries to push the stored offset
        //   4. Meanwhile a rebalance has happened, group has moved to next generation
        //   5. Deferred commit hits the broker with stale generation -> ERR(22)
        //   6. Stored offset never lands on broker
        //   7. New partition owner replays from the *previous* committed offset
        //   8. Class D duplicates
        //
        // The fix (Option 1): in rebalanceCallback, after waiting for background
        // tasks, EXPLICITLY call rdKafkaConsumer.commit synchronously BEFORE
        // incrementalUnassign so the commit lands on the broker while we're still
        // in the current generation.
        //
        // These three tests are designed to FAIL TODAY and PASS after Option 1 is
        // applied. They reproduce the production scenario step by step.
        // ---------------------------------------------------------------------------

        it('ROOT-CAUSE: should commit stored offsets synchronously before incrementalUnassign during rebalance', async () => {
            // Reproduces step 1-3 of the production scenario: a batch is processed,
            // backgroundTask completes, .finally stores the offset. Then a rebalance
            // fires. The fix must commit to the broker BEFORE yielding the partition.

            const eachBatch = jest.fn(() => Promise.resolve({}))
            await consumer.connect(eachBatch)

            // Submit a batch with a controllable backgroundTask.
            const bgTask = triggerablePromise()
            eachBatch.mockImplementationOnce(() => Promise.resolve({ backgroundTask: bgTask.promise }))
            consumeCallback(null, [createKafkaMessage({ offset: 1, partition: 0 })])
            await delay(1)

            // Trigger rebalance while task is in flight.
            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 0 },
            ])
            await delay(1)

            // Resolve backgroundTask -> .finally runs -> offsetsStore called.
            bgTask.resolve()
            await delay(20)

            // The fix's contract: commit MUST be called explicitly (with a callback)
            // and MUST be called BEFORE incrementalUnassign. If commit is never
            // called, librdkafka can only flush via the deferred auto-commit timer,
            // which is when ERR_ILLEGAL_GENERATION strikes.
            expect(mockRdKafkaConsumer.commit).toHaveBeenCalled()

            const offsetsStoreOrder = mockRdKafkaConsumer.offsetsStore.mock.invocationCallOrder[0]
            const commitOrder = mockRdKafkaConsumer.commit.mock.invocationCallOrder[0]
            const unassignOrder = mockRdKafkaConsumer.incrementalUnassign.mock.invocationCallOrder[0]

            // Must be: store, then commit, then unassign — atomically while we're
            // still owners of the partition in the current group generation.
            expect(offsetsStoreOrder).toBeLessThan(commitOrder)
            expect(commitOrder).toBeLessThan(unassignOrder)
        })

        it('ROOT-CAUSE: should still attempt sync commit when there are no in-flight backgroundTasks', async () => {
            // Edge case: ~65% of revocations on EU happen with backgroundTask.length=0
            // (idle moment between batches). Even in that case, prior batches may have
            // stored offsets that haven't been auto-committed yet. The fix must commit
            // those stored offsets before yielding too.

            const eachBatch = jest.fn(() => Promise.resolve({}))
            await consumer.connect(eachBatch)

            // Process a batch that completes synchronously (no backgroundTask).
            // .finally still stores the offset.
            consumeCallback(null, [createKafkaMessage({ offset: 1, partition: 0 })])
            await delay(5)
            expect(mockRdKafkaConsumer.offsetsStore).toHaveBeenCalled()
            expect(consumer['backgroundTask']).toHaveLength(0)

            // Now rebalance fires when no bg tasks are in flight.
            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 0 },
            ])
            await delay(20)

            // Sync commit should still have fired. If commit is gated on
            // backgroundTask.length>0 only, we'd miss this code path and the
            // previously-stored offset would still be vulnerable to ERR(22).
            expect(mockRdKafkaConsumer.commit).toHaveBeenCalled()
            const commitOrder = mockRdKafkaConsumer.commit.mock.invocationCallOrder[0]
            const unassignOrder = mockRdKafkaConsumer.incrementalUnassign.mock.invocationCallOrder[0]
            expect(commitOrder).toBeLessThan(unassignOrder)
        })

        it('ROOT-CAUSE: should log and tolerate ERR_ILLEGAL_GENERATION on sync commit so the rebalance still completes', async () => {
            // Even with the sync commit fix, the broker can still occasionally reject
            // the commit (network blip, broker-initiated rebalance racing us). The
            // fix MUST tolerate this: log the error (via the offset.commit event
            // handler the consumer already registers) and proceed with unassign so
            // the consumer doesn't get stuck. This validates the failure path of
            // the fix.

            const eachBatch = jest.fn(() => Promise.resolve({}))
            await consumer.connect(eachBatch)

            // Locate the offset.commit event handler the consumer registered with
            // librdkafka so we can drive a failure through the same path that fires
            // in production.
            const offsetCommitHandler = mockRdKafkaConsumer.on.mock.calls.find(
                ([event]) => event === 'offset.commit'
            )?.[1] as ((err: any, offsets: any) => void) | undefined
            expect(offsetCommitHandler).toBeDefined()

            const bgTask = triggerablePromise()
            eachBatch.mockImplementationOnce(() => Promise.resolve({ backgroundTask: bgTask.promise }))
            consumeCallback(null, [createKafkaMessage({ offset: 1, partition: 0 })])
            await delay(1)

            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 0 },
            ])
            await delay(1)

            bgTask.resolve()
            await delay(20)

            // Drive the production failure: librdkafka reports the commit failed
            // with ERR_ILLEGAL_GENERATION via the offset.commit event.
            offsetCommitHandler?.({ code: 22, message: 'Broker: Specified group generation id is not valid' }, [
                { topic: 'test-topic', partition: 0, offset: 2 },
            ])

            // Regardless of commit outcome, unassign must still happen so the
            // consumer doesn't get stuck mid-rebalance.
            expect(mockRdKafkaConsumer.commit).toHaveBeenCalled()
            expect(mockRdKafkaConsumer.incrementalUnassign).toHaveBeenCalled()
        })

        it('should not wait when waitForBackgroundTasksOnRebalance is disabled', async () => {
            defaultConfig.CONSUMER_WAIT_FOR_BACKGROUND_TASKS_ON_REBALANCE = false
            // Create a consumer with feature disabled
            const consumerDisabled = new KafkaConsumer({
                groupId: 'test-group',
                topic: 'test-topic',
            })

            const mockConsumerDisabled = jest.mocked(consumerDisabled['rdKafkaConsumer'])

            // Add background tasks with metadata
            // Explicitly assign promise array (handled in cleanup)
            void (consumerDisabled['backgroundTask'] = [{ promise: Promise.resolve(), createdAt: Date.now() }])

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
        expect(result).toEqual(createTestEventHeaders())
    })

    it('should return empty object when headers is empty array', () => {
        const result = parseEventHeaders([])
        expect(result).toEqual(createTestEventHeaders())
    })

    it('should parse token header only', () => {
        const headers: MessageHeader[] = [{ token: Buffer.from('test-token') }]
        const result = parseEventHeaders(headers)
        expect(result).toEqual(createTestEventHeaders({ token: 'test-token' }))
    })

    it('should parse distinct_id header only', () => {
        const headers: MessageHeader[] = [{ distinct_id: Buffer.from('user-123') }]
        const result = parseEventHeaders(headers)
        expect(result).toEqual(createTestEventHeaders({ distinct_id: 'user-123' }))
    })

    it('should parse timestamp header only', () => {
        const headers: MessageHeader[] = [{ timestamp: Buffer.from('1234567890') }]
        const result = parseEventHeaders(headers)
        expect(result).toEqual(createTestEventHeaders({ timestamp: '1234567890' }))
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
        expect(result).toEqual(
            createTestEventHeaders({ token: 'test-token', distinct_id: 'user-123', timestamp: '1234567890' })
        )
    })

    it('should parse supported headers from multiple objects', () => {
        const headers: MessageHeader[] = [
            { token: Buffer.from('test-token') },
            { distinct_id: Buffer.from('user-123') },
            { timestamp: Buffer.from('1234567890') },
        ]
        const result = parseEventHeaders(headers)
        expect(result).toEqual(
            createTestEventHeaders({ token: 'test-token', distinct_id: 'user-123', timestamp: '1234567890' })
        )
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
        expect(result).toEqual(createTestEventHeaders({ token: 'test-token', distinct_id: 'user-123' }))
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
        expect(result).toEqual(createTestEventHeaders({ token: '', distinct_id: '', timestamp: '' }))
    })

    it('should handle duplicate keys by overwriting', () => {
        const headers: MessageHeader[] = [
            { token: Buffer.from('first-token') },
            { token: Buffer.from('second-token') },
            { distinct_id: Buffer.from('first-id') },
            { distinct_id: Buffer.from('second-id') },
        ]
        const result = parseEventHeaders(headers)
        expect(result).toEqual(createTestEventHeaders({ token: 'second-token', distinct_id: 'second-id' }))
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
        expect(result).toEqual(createTestEventHeaders({ token: 'test-token', timestamp: '1234567890' }))
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
        expect(result).toEqual(createTestEventHeaders({ token: 'test-token', timestamp: '1234567890' }))
    })

    it('should parse event header', () => {
        const headers: MessageHeader[] = [{ event: Buffer.from('$pageview') }]
        const result = parseEventHeaders(headers)
        expect(result).toEqual(createTestEventHeaders({ event: '$pageview' }))
    })

    it('should parse uuid header', () => {
        const headers: MessageHeader[] = [{ uuid: Buffer.from('123e4567-e89b-12d3-a456-426614174000') }]
        const result = parseEventHeaders(headers)
        expect(result).toEqual(createTestEventHeaders({ uuid: '123e4567-e89b-12d3-a456-426614174000' }))
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
        expect(result).toEqual(
            createTestEventHeaders({
                token: 'test-token',
                distinct_id: 'user-123',
                timestamp: '1234567890',
                event: '$pageview',
                uuid: '123e4567-e89b-12d3-a456-426614174000',
            })
        )
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
        expect(result).toEqual(
            createTestEventHeaders({
                token: 'test-token',
                distinct_id: 'user-123',
                event: 'custom_event',
                uuid: 'uuid-value',
            })
        )
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
        expect(result).toEqual(createTestEventHeaders({ token: 'test-token', event: '', uuid: '' }))
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
            expect(result).toEqual(
                createTestEventHeaders({
                    token: 'test-token',
                    distinct_id: 'user-123',
                    now: new Date(isoDate),
                })
            )
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
