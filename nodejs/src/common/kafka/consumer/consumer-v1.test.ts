import { CODES, Message, MessageHeader, KafkaConsumer as RdKafkaConsumer } from 'node-rdkafka'

import { createTestEventHeaders } from '~/tests/helpers/event-headers'

import { delay } from '../../utils/utils'
import { KafkaConsumer, parseEventHeaders, parseKafkaHeaders } from './consumer-v1'

jest.mock('../admin', () => ({
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
        }

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

    // auto.offset.reset is a topic-level librdkafka property, and a value only in the global
    // config is ignored, so an override must be mirrored into the topic config (2nd ctor arg).
    it.each([
        [
            'mirrors an auto.offset.reset override into the topic config',
            { 'auto.offset.reset': 'latest' } as any,
            'latest',
        ],
        ['defaults the topic-config auto.offset.reset to earliest with no override', undefined, 'earliest'],
    ])('%s', (_label, overrides, expected) => {
        const RdKafkaCtor = jest.mocked(RdKafkaConsumer)
        new KafkaConsumer({ groupId: 'g', topic: 't' }, overrides)
        const topicConfig = RdKafkaCtor.mock.calls.at(-1)![1] as any
        expect(topicConfig['auto.offset.reset']).toBe(expected)
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

        const watchLoopOutcome = (): Promise<unknown> =>
            Promise.race([
                consumer['consumerLoop']!.then(
                    () => 'stopped cleanly',
                    (error) => error
                ),
                delay(50).then(() => 'still consuming'),
            ])

        it('stores no offsets once a background task fails, and stops the loop so the batch replays', async () => {
            const failure = new Error('Connection terminated unexpectedly')
            const p1 = triggerablePromise()
            await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 1, partition: 0 })], p1.promise)
            const p2 = triggerablePromise()
            await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 2, partition: 0 })], p2.promise)
            const loopOutcome = watchLoopOutcome()

            p1.reject(failure)
            p2.resolve()
            await delay(1)
            consumeCallback(null, [])
            await delay(1)

            expect(mockRdKafkaConsumer.offsetsStore).not.toHaveBeenCalled()
            await expect(loopOutcome).resolves.toBe(failure)
        })

        type SettleStep = { resolve: number } | { reject: number } | { dispatchWithoutBackgroundTask: number }

        it.each<{ name: string; pendingBatches: number; steps: SettleStep[]; storedOffsets: number[] }>([
            {
                name: 'the later batch fulfils first, then the earlier batch rejects',
                pendingBatches: 2,
                steps: [{ resolve: 2 }, { reject: 1 }],
                storedOffsets: [],
            },
            {
                name: 'the first batch fulfils, the second rejects, then the third fulfils',
                pendingBatches: 3,
                steps: [{ resolve: 1 }, { reject: 2 }, { resolve: 3 }],
                storedOffsets: [2],
            },
            {
                name: 'the middle batch rejects while the first is pending, then the first and third fulfil',
                pendingBatches: 3,
                steps: [{ reject: 2 }, { resolve: 1 }, { resolve: 3 }],
                storedOffsets: [],
            },
            {
                name: 'a batch with no background task arrives after a rejection',
                pendingBatches: 1,
                steps: [{ reject: 1 }, { dispatchWithoutBackgroundTask: 2 }],
                storedOffsets: [],
            },
        ])(
            'stores no offsets for a batch that settles after a failure when $name',
            async ({ pendingBatches, steps, storedOffsets }) => {
                const tasks: ReturnType<typeof triggerablePromise>[] = []
                for (let offset = 1; offset <= pendingBatches; offset++) {
                    const task = triggerablePromise()
                    tasks.push(task)
                    await simulateMessageWithBackgroundTask(
                        [createKafkaMessage({ offset, partition: 0 })],
                        task.promise
                    )
                }
                void consumer['consumerLoop']!.catch(() => {})

                for (const step of steps) {
                    if ('resolve' in step) {
                        tasks[step.resolve - 1].resolve()
                    } else if ('reject' in step) {
                        tasks[step.reject - 1].reject(new Error('background task failed'))
                    } else {
                        consumeCallback(null, [
                            createKafkaMessage({ offset: step.dispatchWithoutBackgroundTask, partition: 0 }),
                        ])
                    }
                    await delay(1)
                }

                expect(mockRdKafkaConsumer.offsetsStore.mock.calls.map(([offsets]) => offsets[0].offset)).toEqual(
                    storedOffsets
                )
            }
        )

        it.each([undefined, null, 0, '', false])(
            'stores no offsets and stops the loop with an Error when a background task rejects with %p',
            async (reason) => {
                const p1 = triggerablePromise()
                await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 1, partition: 0 })], p1.promise)
                const p2 = triggerablePromise()
                await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 2, partition: 0 })], p2.promise)
                const loopOutcome = watchLoopOutcome()

                p1.reject(reason)
                p2.resolve()
                await delay(1)
                consumeCallback(null, [])
                await delay(1)

                expect(mockRdKafkaConsumer.offsetsStore).not.toHaveBeenCalled()
                await expect(loopOutcome).resolves.toBeInstanceOf(Error)
            }
        )

        it('stores no offsets and removes no other task when its own task is missing from the queue', async () => {
            const p1 = triggerablePromise()
            const other = triggerablePromise()
            await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 1, partition: 0 })], p1.promise)
            consumer['backgroundTask'] = [{ promise: other.promise, createdAt: Date.now() }]

            p1.resolve()
            await delay(1)

            expect(mockRdKafkaConsumer.offsetsStore).not.toHaveBeenCalled()
            expect(consumer['backgroundTask'].map((t) => t.promise)).toEqual([other.promise])
            other.resolve()
        })

        it('stores no offsets for a background task that rejects during disconnect, and still disconnects', async () => {
            const p1 = triggerablePromise()
            await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 1, partition: 0 })], p1.promise)
            const loopOutcome = watchLoopOutcome()
            const disconnecting = consumer.disconnect().catch(() => {})

            p1.reject(undefined)
            consumeCallback(null, [])
            await disconnecting

            await expect(loopOutcome).resolves.toBeInstanceOf(Error)
            expect(mockRdKafkaConsumer.offsetsStore).not.toHaveBeenCalled()
            expect(mockRdKafkaConsumer.disconnect).toHaveBeenCalled()
        })

        it('stores no offsets for a background task that rejects during a revoke, and still unassigns', async () => {
            mockRdKafkaConsumer.assignments.mockReturnValue([])
            const p1 = triggerablePromise()
            await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 1, partition: 0 })], p1.promise)
            void consumer['consumerLoop']!.catch(() => {})

            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 0 },
            ])
            p1.reject(new Error('background task failed'))
            await delay(1)

            expect(mockRdKafkaConsumer.incrementalUnassign).toHaveBeenCalledWith([
                { topic: 'test-topic', partition: 0 },
            ])
            expect(mockRdKafkaConsumer.offsetsStore).not.toHaveBeenCalled()
        })

        it.each([new Error('background task failed'), undefined, 0])(
            'refuses a manual offsetsStore after a background task rejects with %p',
            async (reason) => {
                const offsets = [{ topic: 'test-topic', partition: 0, offset: 1 }]
                consumer.offsetsStore(offsets)
                expect(mockRdKafkaConsumer.offsetsStore).toHaveBeenCalledWith(offsets)

                const p1 = triggerablePromise()
                await simulateMessageWithBackgroundTask([createKafkaMessage({ offset: 1, partition: 0 })], p1.promise)
                void consumer['consumerLoop']!.catch(() => {})
                p1.reject(reason)
                await delay(1)
                mockRdKafkaConsumer.offsetsStore.mockClear()

                expect(() => consumer.offsetsStore(offsets)).toThrow()
                expect(mockRdKafkaConsumer.offsetsStore).not.toHaveBeenCalled()
            }
        )
    })

    describe('rebalancing', () => {
        it('should clear rebalancing state during partition assignment', () => {
            consumer['rebalanceCoordination'].isRebalancing = true

            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__ASSIGN_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 1 },
            ])

            expect(consumer['rebalanceCoordination'].isRebalancing).toBe(false)
        })

        it('should unassign, call the revoke hook and resume consuming when no background tasks exist', async () => {
            consumer['backgroundTask'] = []
            mockRdKafkaConsumer.assignments.mockReturnValue([{ topic: 'test-topic', partition: 2 }])
            const onPartitionsRevoked = jest.fn().mockResolvedValue(undefined)
            consumer['onPartitionsRevoked'] = onPartitionsRevoked

            consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, [
                { topic: 'test-topic', partition: 1 },
            ])

            await delay(1)
            expect(mockRdKafkaConsumer.incrementalUnassign).toHaveBeenCalledWith([
                { topic: 'test-topic', partition: 1 },
            ])
            expect(consumer['rebalanceCoordination'].isRebalancing).toBe(false)
            expect(onPartitionsRevoked).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 1 }])
        })

        it('should resume consuming when unassigning revoked partitions throws', () => {
            consumer['backgroundTask'] = []
            mockRdKafkaConsumer.incrementalUnassign.mockImplementation(() => {
                throw new Error('KafkaConsumer is not connected')
            })

            expect(() =>
                consumer.rebalanceCallback({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, [
                    { topic: 'test-topic', partition: 1 },
                ])
            ).toThrow('KafkaConsumer is not connected')
            expect(consumer['rebalanceCoordination'].isRebalancing).toBe(false)
        })

        it('should wait for background tasks before calling incrementalUnassign', async () => {
            mockRdKafkaConsumer.assignments.mockReturnValue([{ topic: 'test-topic', partition: 2 }])
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
            expect(consumer['rebalanceCoordination'].isRebalancing).toBe(false)
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
