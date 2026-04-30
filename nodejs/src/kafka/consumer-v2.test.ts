import { CODES, Message, KafkaConsumer as RdKafkaConsumer } from 'node-rdkafka'

import { delay } from '../utils/utils'
import { KafkaConsumerV2 } from './consumer-v2'

jest.mock('./admin', () => ({ ensureTopicExists: jest.fn().mockResolvedValue(undefined) }))

jest.mock('node-rdkafka', () => ({
    KafkaConsumer: jest.fn(),
    CODES: {
        ERRORS: {
            ERR__REVOKE_PARTITIONS: 'ERR__REVOKE_PARTITIONS',
            ERR__ASSIGN_PARTITIONS: 'ERR__ASSIGN_PARTITIONS',
        },
    },
}))

const createMessage = (m: Partial<Message> = {}): Message => ({
    value: Buffer.from('test-value'),
    key: Buffer.from('test-key'),
    offset: 1,
    partition: 0,
    topic: 'test-topic',
    size: 10,
    ...m,
})

jest.setTimeout(15000)

const activePromiseResolvers: Array<() => void> = []

const triggerablePromise = <T = unknown>(): {
    promise: Promise<T>
    resolve: (value?: T) => void
    reject: (reason?: unknown) => void
} => {
    const result = {
        promise: null as unknown as Promise<T>,
        resolve: () => {},
        reject: () => {},
    } as {
        promise: Promise<T>
        resolve: (value?: T) => void
        reject: (reason?: unknown) => void
    }

    result.promise = new Promise((resolve, reject) => {
        const wrappedResolve = (value?: T) => {
            const i = activePromiseResolvers.indexOf(wrappedResolve)
            if (i > -1) {
                activePromiseResolvers.splice(i, 1)
            }
            resolve(value as T)
        }
        result.resolve = wrappedResolve
        result.reject = (reason?: unknown) => {
            const i = activePromiseResolvers.indexOf(wrappedResolve)
            if (i > -1) {
                activePromiseResolvers.splice(i, 1)
            }
            reject(reason)
        }
        activePromiseResolvers.push(wrappedResolve)
    })
    return result
}

describe('KafkaConsumerV2', () => {
    let consumer: KafkaConsumerV2
    let mockRdKafka: jest.Mocked<RdKafkaConsumer>
    let consumeCallback: ((error: Error | null, messages: Message[]) => void) | undefined
    let registeredRebalanceCb: ((err: any, partitions: any[]) => void) | undefined

    beforeEach(() => {
        consumeCallback = undefined
        registeredRebalanceCb = undefined

        const mockInstance: any = {
            connect: jest.fn().mockImplementation((_: unknown, cb: (err: Error | null) => void) => cb(null)),
            subscribe: jest.fn(),
            consume: jest.fn().mockImplementation((_: unknown, cb: any) => {
                consumeCallback = cb
            }),
            disconnect: jest.fn().mockImplementation((cb: (err: Error | null) => void) => cb(null)),
            isConnected: jest.fn().mockReturnValue(true),
            on: jest.fn(),
            assignments: jest.fn().mockReturnValue([]),
            offsetsStore: jest.fn(),
            setDefaultConsumeTimeout: jest.fn(),
            incrementalUnassign: jest.fn(),
            incrementalAssign: jest.fn(),
            assign: jest.fn(),
            unassign: jest.fn(),
            rebalanceProtocol: jest.fn().mockReturnValue('COOPERATIVE'),
        }

        // Capture the rebalance callback the consumer registers via rdKafkaConfig
        const RdKafkaCtor = jest.mocked(require('node-rdkafka').KafkaConsumer)
        RdKafkaCtor.mockImplementation((config: any) => {
            registeredRebalanceCb = config.rebalance_cb
            return mockInstance
        })

        consumer = new KafkaConsumerV2({ groupId: 'test-group', topic: 'test-topic' })
        mockRdKafka = mockInstance
    })

    afterEach(async () => {
        // Drop any in-flight tasks before disconnect to avoid 60s timeout waits.
        if (consumer && (consumer as any).inFlight) {
            ;(consumer as any).inFlight = []
        }
        while (activePromiseResolvers.length > 0) {
            activePromiseResolvers[0]()
        }
        if (consumer) {
            const p = consumer.disconnect()
            // Release any pending consume callback so the loop can exit.
            if (consumeCallback) {
                consumeCallback(null, [])
            }
            await p
        }
    })

    /** Drive the consumer through ASSIGN so it transitions to CONSUMING. */
    const startConsuming = async (eachBatch: jest.Mock, partitions = [{ topic: 'test-topic', partition: 0 }]) => {
        await consumer.connect(eachBatch)
        registeredRebalanceCb!({ code: CODES.ERRORS.ERR__ASSIGN_PARTITIONS } as any, partitions)
        // The loop is currently inside the IDLE keepalive consume(1, cb). Release it with
        // an empty batch so the loop processes ASSIGN and arms a fresh consume() in CONSUMING.
        if (consumeCallback) {
            const cb = consumeCallback
            consumeCallback = undefined
            cb(null, [])
        }
        await delay(5)
    }

    /** Release the in-flight consume(), if any, with empty messages so the loop can iterate. */
    const releaseConsume = () => {
        if (consumeCallback) {
            const cb = consumeCallback
            consumeCallback = undefined
            cb(null, [])
        }
    }

    const fireRevoke = (partitions = [{ topic: 'test-topic', partition: 0 }]) => {
        registeredRebalanceCb!({ code: CODES.ERRORS.ERR__REVOKE_PARTITIONS } as any, partitions)
        // librdkafka delivers REVOKE on the same thread as consume() returns; simulate that.
        releaseConsume()
    }

    const fireAssign = (partitions = [{ topic: 'test-topic', partition: 0 }]) => {
        registeredRebalanceCb!({ code: CODES.ERRORS.ERR__ASSIGN_PARTITIONS } as any, partitions)
        releaseConsume()
    }

    /** Deliver a batch + a controllable backgroundTask. Resolves when the task is in-flight. */
    const dispatchBatch = async (
        eachBatch: jest.Mock,
        messages: Message[],
        backgroundTask?: Promise<unknown>
    ): Promise<void> => {
        eachBatch.mockImplementationOnce(() =>
            backgroundTask !== undefined ? Promise.resolve({ backgroundTask }) : Promise.resolve({})
        )
        consumeCallback!(null, messages)
        await delay(2)
    }

    it('Smoke: connect → consume → eachBatch → offsets stored', async () => {
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        consumeCallback!(null, [createMessage({ offset: 1, partition: 0 })])
        await delay(5)

        expect(eachBatch).toHaveBeenCalledWith([createMessage({ offset: 1, partition: 0 })])
        expect(mockRdKafka.offsetsStore).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0, offset: 2 }])
    })

    it('Backpressure: pushing > maxBackgroundTasks blocks until oldest settles', async () => {
        ;(consumer as any).maxBackgroundTasks = 2
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        const p1 = triggerablePromise()
        const p2 = triggerablePromise()
        const p3 = triggerablePromise()

        await dispatchBatch(eachBatch, [createMessage({ offset: 1, partition: 0 })], p1.promise)
        await dispatchBatch(eachBatch, [createMessage({ offset: 2, partition: 0 })], p2.promise)
        await dispatchBatch(eachBatch, [createMessage({ offset: 3, partition: 0 })], p3.promise)
        await delay(2)

        // Loop is blocked on backpressure; consume() should NOT have been called for batch 4.
        const callsBefore = mockRdKafka.consume.mock.calls.length
        p1.resolve()
        await delay(5)
        expect(mockRdKafka.consume.mock.calls.length).toBeGreaterThan(callsBefore)
    })

    it('REVOKE drain: incrementalUnassign called only after every settled completes', async () => {
        ;(consumer as any).maxBackgroundTasks = 5
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        const p1 = triggerablePromise()
        const p2 = triggerablePromise()
        await dispatchBatch(eachBatch, [createMessage({ offset: 1, partition: 0 })], p1.promise)
        await dispatchBatch(eachBatch, [createMessage({ offset: 2, partition: 0 })], p2.promise)

        fireRevoke()
        await delay(5)
        expect(mockRdKafka.incrementalUnassign).not.toHaveBeenCalled()

        p1.resolve()
        await delay(5)
        expect(mockRdKafka.incrementalUnassign).not.toHaveBeenCalled()

        p2.resolve()
        await delay(20)
        expect(mockRdKafka.incrementalUnassign).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0 }])
    })

    it('H1 regression: task pushed during the rebalance window is awaited before unassign', async () => {
        ;(consumer as any).maxBackgroundTasks = 5
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        const p1 = triggerablePromise()
        const p2 = triggerablePromise()
        await dispatchBatch(eachBatch, [createMessage({ offset: 1, partition: 0 })], p1.promise)
        await dispatchBatch(eachBatch, [createMessage({ offset: 2, partition: 0 })], p2.promise)

        // Set up a third batch where eachBatch is in flight when the rebalance fires.
        const p3 = triggerablePromise()
        const eachBatchGate = triggerablePromise()
        eachBatch.mockImplementationOnce(async () => {
            await eachBatchGate.promise
            return { backgroundTask: p3.promise }
        })
        consumeCallback!(null, [createMessage({ offset: 3, partition: 0 })])
        await delay(2)

        // Fire revoke while eachBatch is still awaiting the gate.
        fireRevoke()
        await delay(2)

        // Release eachBatch — even though we're now DRAINING, the task is tracked and drainAll
        // awaits its settled promise. (This is the H1 fix: tasks pushed during the rebalance
        // window are NOT excluded from drain.)
        eachBatchGate.resolve()
        await delay(5)

        // Resolve t1 + t2 only. t3 still pending.
        p1.resolve()
        p2.resolve()
        await delay(10)
        expect(mockRdKafka.incrementalUnassign).not.toHaveBeenCalled()

        // Resolving t3 unblocks drain.
        p3.resolve()
        await delay(20)
        expect(mockRdKafka.incrementalUnassign).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0 }])
    })

    it('H2 regression: stale tasks across generations skip storeOffsets and never trigger unassign', async () => {
        ;(consumer as any).maxBackgroundTasks = 5
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        const slow = triggerablePromise()
        await dispatchBatch(eachBatch, [createMessage({ offset: 1, partition: 0 })], slow.promise)

        // Fire revoke; drain begins.
        fireRevoke()
        await delay(2)
        expect(mockRdKafka.incrementalUnassign).not.toHaveBeenCalled()

        // Resolve slow. Drain completes, unassign fires synchronously inside the loop.
        slow.resolve()
        await delay(20)
        expect(mockRdKafka.incrementalUnassign).toHaveBeenCalledTimes(1)

        // Now simulate cooperative-sticky reassign of the same partition.
        mockRdKafka.incrementalUnassign.mockClear()
        fireAssign()
        await delay(5)
        expect(mockRdKafka.incrementalAssign).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0 }])

        // No deferred .then armed — no bogus unassign of the just-reassigned partition.
        await delay(20)
        expect(mockRdKafka.incrementalUnassign).not.toHaveBeenCalled()
    })

    it('H3 regression: out-of-order task completion does not race storeOffsets against unassign', async () => {
        ;(consumer as any).maxBackgroundTasks = 5
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        const p1 = triggerablePromise()
        const p2 = triggerablePromise()
        await dispatchBatch(eachBatch, [createMessage({ offset: 1, partition: 0 })], p1.promise)
        await dispatchBatch(eachBatch, [createMessage({ offset: 2, partition: 0 })], p2.promise)

        const callOrder: string[] = []
        ;(mockRdKafka.offsetsStore as jest.Mock).mockImplementation(() => {
            callOrder.push('offsetsStore')
        })
        ;(mockRdKafka.incrementalUnassign as jest.Mock).mockImplementation(() => {
            callOrder.push('incrementalUnassign')
        })

        fireRevoke()
        await delay(2)

        // Out-of-order: t2 first, then t1.
        p2.resolve()
        await delay(2)
        p1.resolve()
        await delay(20)

        expect(callOrder).toContain('incrementalUnassign')
        const lastStore = callOrder.lastIndexOf('offsetsStore')
        const unassign = callOrder.indexOf('incrementalUnassign')
        // ALL stores must precede the unassign.
        expect(unassign).toBeGreaterThan(lastStore)
    })

    it('Drain timeout: never-settling task is force-released after drainTimeoutMs', async () => {
        ;(consumer as any).drainTimeoutMs = 50
        ;(consumer as any).maxBackgroundTasks = 5
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        const stuck = triggerablePromise()
        await dispatchBatch(eachBatch, [createMessage({ offset: 1, partition: 0 })], stuck.promise)

        fireRevoke()
        await delay(120)

        // Drain timed out; loop proceeded with unassign.
        expect(mockRdKafka.incrementalUnassign).toHaveBeenCalled()
    })

    it('ASSIGN after REVOKE: state transitions back to CONSUMING and resumes fetching', async () => {
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        fireRevoke()
        await delay(20)
        expect(mockRdKafka.incrementalUnassign).toHaveBeenCalled()

        const callsBeforeAssign = mockRdKafka.consume.mock.calls.length
        fireAssign([{ topic: 'test-topic', partition: 1 }])
        await delay(10)
        expect(mockRdKafka.incrementalAssign).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 1 }])
        // After ASSIGN, the loop transitions back to CONSUMING and immediately calls consume().
        expect(mockRdKafka.consume.mock.calls.length).toBeGreaterThan(callsBeforeAssign)
    })

    it('Disconnect drains in-flight tasks before tearing down', async () => {
        ;(consumer as any).maxBackgroundTasks = 5
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        const slow = triggerablePromise()
        await dispatchBatch(eachBatch, [createMessage({ offset: 1, partition: 0 })], slow.promise)

        const disconnectPromise = consumer.disconnect()

        // Force the in-flight consume to release so the loop can observe state=STOPPED.
        if (consumeCallback) {
            consumeCallback(null, [])
        }

        // disconnect should be pending until slow resolves.
        await delay(20)
        expect(mockRdKafka.disconnect).not.toHaveBeenCalled()

        slow.resolve()
        await disconnectPromise
        expect(mockRdKafka.offsetsStore).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0, offset: 2 }])
        expect(mockRdKafka.disconnect).toHaveBeenCalled()
        // Avoid double-disconnect in afterEach.
        consumer = undefined as unknown as KafkaConsumerV2
    })

    it('eachBatch returning void: offsets still stored', async () => {
        const eachBatch = jest.fn(() => Promise.resolve())
        await startConsuming(eachBatch)

        consumeCallback!(null, [createMessage({ offset: 5, partition: 0 })])
        await delay(5)

        expect(mockRdKafka.offsetsStore).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0, offset: 6 }])
    })

    it('eachBatch throwing: error logged, offsets NOT stored, loop continues', async () => {
        const eachBatch = jest
            .fn()
            .mockImplementationOnce(() => Promise.reject(new Error('boom')))
            .mockImplementation(() => Promise.resolve())
        await startConsuming(eachBatch)

        consumeCallback!(null, [createMessage({ offset: 7, partition: 0 })])
        await delay(10)

        expect(mockRdKafka.offsetsStore).not.toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0, offset: 8 }])

        // Next batch should still be fetched + processed.
        consumeCallback!(null, [createMessage({ offset: 8, partition: 0 })])
        await delay(10)
        expect(eachBatch).toHaveBeenCalledTimes(2)
        expect(mockRdKafka.offsetsStore).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0, offset: 9 }])
    })

    it('callEachBatchWhenEmpty: empty batches still call eachBatch', async () => {
        consumer = (() => {
            jest.mocked(require('node-rdkafka').KafkaConsumer)
            return new KafkaConsumerV2({
                groupId: 'test-group-empty',
                topic: 'test-topic',
                callEachBatchWhenEmpty: true,
            })
        })()
        mockRdKafka = jest.mocked((consumer as any).rdKafkaConsumer)

        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        consumeCallback!(null, [])
        await delay(5)

        expect(eachBatch).toHaveBeenCalledWith([])
    })

    it('autoOffsetStore=false: storeOffsets never called automatically', async () => {
        consumer = (() => {
            return new KafkaConsumerV2({
                groupId: 'test-group-manual',
                topic: 'test-topic',
                autoOffsetStore: false,
            })
        })()
        mockRdKafka = jest.mocked((consumer as any).rdKafkaConsumer)

        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        consumeCallback!(null, [createMessage({ offset: 9, partition: 0 })])
        await delay(5)

        expect(mockRdKafka.offsetsStore).not.toHaveBeenCalled()

        // Manual path still works.
        consumer.offsetsStore([{ topic: 'test-topic', partition: 0, offset: 10 }])
        expect(mockRdKafka.offsetsStore).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0, offset: 10 }])
    })

    it('Generation tag: a settle that fires after a generation bump skips storeOffsets', async () => {
        ;(consumer as any).maxBackgroundTasks = 5
        ;(consumer as any).drainTimeoutMs = 30 // force drain timeout so generation bump precedes resolve
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        const slow = triggerablePromise()
        await dispatchBatch(eachBatch, [createMessage({ offset: 1, partition: 0 })], slow.promise)

        fireRevoke()
        // Drain times out → loop calls incrementalUnassign → state goes IDLE; generation bumped.
        await delay(60)
        expect(mockRdKafka.incrementalUnassign).toHaveBeenCalled()

        // Resolve the slow task AFTER generation bump.
        slow.resolve()
        await delay(20)

        // storeOffsets should NOT be called for this stale task.
        expect(mockRdKafka.offsetsStore).not.toHaveBeenCalled()
    })

    it('Health: not connected → error', () => {
        ;(mockRdKafka.isConnected as jest.Mock).mockReturnValue(false)
        const result = consumer.isHealthy()
        expect(result.isError()).toBe(true)
    })

    it('Health: connected and recently ticked → ok', async () => {
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)
        expect(consumer.isHealthy().isError()).toBe(false)
    })
})

afterAll(() => {
    // Belt and braces — make sure no tracked promises leak between files.
    while (activePromiseResolvers.length > 0) {
        activePromiseResolvers[0]()
    }
})
