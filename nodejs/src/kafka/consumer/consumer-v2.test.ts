import { CODES, Message, KafkaConsumer as RdKafkaConsumer } from 'node-rdkafka'

import { captureException } from '../../utils/posthog'
import { delay } from '../../utils/utils'
import { KafkaConsumerV2 } from './consumer-v2'

jest.mock('../admin', () => ({ ensureTopicExists: jest.fn().mockResolvedValue(undefined) }))

// Spy on captureException to assert that the IDLE-keepalive invariant fires when violated.
jest.mock('../../utils/posthog', () => ({
    captureException: jest.fn(),
}))

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
        ;(captureException as jest.Mock).mockClear()

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

        // Validate the fix mechanism, not just the outcome: all 3 tasks are tracked in inFlight,
        // including t3 which was dispatched AFTER REVOKE arrived.
        expect((consumer as any).inFlight.length).toBe(3)

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
        // The slow task crossed the rebalance generation — its storeOffsets MUST have been
        // skipped (generation-tag mechanism). Validates the H2 protection directly.
        expect(mockRdKafka.offsetsStore).not.toHaveBeenCalled()

        // Snapshot offsetsStore + unassign call counts before the reassign so we can assert
        // nothing further happens once we re-acquire the partition.
        const offsetCallsBeforeReassign = mockRdKafka.offsetsStore.mock.calls.length
        mockRdKafka.incrementalUnassign.mockClear()

        // Now simulate cooperative-sticky reassign of the same partition.
        fireAssign()
        await delay(5)
        expect(mockRdKafka.incrementalAssign).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0 }])

        // No deferred .then armed — no bogus unassign and no surprise offset writes against
        // the just-reassigned partition.
        await delay(20)
        expect(mockRdKafka.incrementalUnassign).not.toHaveBeenCalled()
        expect(mockRdKafka.offsetsStore.mock.calls.length).toBe(offsetCallsBeforeReassign)
    })

    it('H3 regression: out-of-order task completion — drain awaits ALL settled before unassign', async () => {
        // The v1 H3 race was: drain awaited t.promise (raw), so the late task's storeOffsets
        // could fire AFTER incrementalUnassign. v2 fixes this two ways:
        //   (a) drain awaits the post-storeOffsets `settled` chain, not the raw task; and
        //   (b) the generation tag in trackTask makes any storeOffsets call during DRAINING
        //       a no-op (see the "Generation tag" test).
        //
        // (b) means we can't meaningfully assert offsetsStore-vs-unassign ordering during a
        // REVOKE — storeOffsets simply never runs in that path. So this test verifies the
        // (a) property directly: with two tasks resolving out of order, drainAll awaits both
        // settled callbacks before incrementalUnassign fires. If drain awaited only `raw`,
        // it could fire before the second task settled.
        ;(consumer as any).maxBackgroundTasks = 5
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        const p1 = triggerablePromise()
        const p2 = triggerablePromise()
        await dispatchBatch(eachBatch, [createMessage({ offset: 1, partition: 0 })], p1.promise)
        await dispatchBatch(eachBatch, [createMessage({ offset: 2, partition: 0 })], p2.promise)

        fireRevoke()
        await delay(2)
        expect(mockRdKafka.incrementalUnassign).not.toHaveBeenCalled()

        // Resolve out of order — t2 finishes first.
        p2.resolve()
        await delay(10)
        // Drain still awaits t1's settled — unassign must NOT have fired yet.
        expect(mockRdKafka.incrementalUnassign).not.toHaveBeenCalled()

        // Now t1 settles → drain completes → unassign fires.
        p1.resolve()
        await delay(20)
        expect(mockRdKafka.incrementalUnassign).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0 }])
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

    it('REVOKE without follow-up ASSIGN: loop stays alive and keeps polling', async () => {
        // Validates that if librdkafka revokes our partitions and never re-assigns (e.g. the
        // group went down to one consumer), the loop doesn't wedge — it keeps calling
        // consume() to drive heartbeats and the next rebalance.
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        fireRevoke()
        await delay(20)
        expect(mockRdKafka.incrementalUnassign).toHaveBeenCalled()

        // No fireAssign() — drive several polls.
        const callsBefore = mockRdKafka.consume.mock.calls.length
        for (let i = 0; i < 5; i++) {
            if (consumeCallback) {
                const cb = consumeCallback
                consumeCallback = undefined
                cb(null, [])
            }
            await delay(5)
        }
        expect(mockRdKafka.consume.mock.calls.length).toBeGreaterThan(callsBefore)
        // Loop still running — not crashed.
        expect((consumer as any).running).toBe(true)
    })

    it('Sticky reassign roundtrip: REVOKE [P0] → ASSIGN [P0] back, no stuck or duplicate work', async () => {
        // Validates the cooperative-sticky case where the broker takes our partition then
        // gives it right back. v1's H2 bug fired here because of a stale deferred .then;
        // v2's drain-inside-loop design must handle this cleanly.
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        fireRevoke([{ topic: 'test-topic', partition: 0 }])
        await delay(20)
        expect(mockRdKafka.incrementalUnassign).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0 }])

        const unassignCallsBeforeReassign = mockRdKafka.incrementalUnassign.mock.calls.length

        fireAssign([{ topic: 'test-topic', partition: 0 }])
        await delay(20)
        expect(mockRdKafka.incrementalAssign).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0 }])

        // Critical: no spurious unassign of the just-reassigned partition.
        expect(mockRdKafka.incrementalUnassign.mock.calls.length).toBe(unassignCallsBeforeReassign)
    })

    it('Incremental ASSIGN: a second ASSIGN with new partitions extends the assignment', async () => {
        // With cooperative-sticky, a rebalance can deliver an ASSIGN for new partitions
        // without first revoking the existing ones. The handler must call
        // incrementalAssign() so existing partitions stay assigned.
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch, [{ topic: 'test-topic', partition: 0 }])

        // Now a second ASSIGN comes in for partition 1 (cooperative add).
        fireAssign([{ topic: 'test-topic', partition: 1 }])
        await delay(10)

        // incrementalAssign was called twice — once per ASSIGN event — never assign().
        expect(mockRdKafka.incrementalAssign).toHaveBeenNthCalledWith(1, [{ topic: 'test-topic', partition: 0 }])
        expect(mockRdKafka.incrementalAssign).toHaveBeenNthCalledWith(2, [{ topic: 'test-topic', partition: 1 }])
        expect(mockRdKafka.assign).not.toHaveBeenCalled()
        expect(mockRdKafka.incrementalUnassign).not.toHaveBeenCalled()
    })

    it('Partial REVOKE: only the revoked partition is unassigned, drain awaits in-flight task', async () => {
        // Cooperative-sticky drops a subset; we await the in-flight task before
        // unassigning, and only call incrementalUnassign for the revoked partition.
        ;(consumer as any).maxBackgroundTasks = 5
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch, [
            { topic: 'test-topic', partition: 0 },
            { topic: 'test-topic', partition: 1 },
        ])

        const p1 = triggerablePromise()
        await dispatchBatch(eachBatch, [createMessage({ offset: 1, partition: 0 })], p1.promise)

        fireRevoke([{ topic: 'test-topic', partition: 1 }])
        await delay(5)

        // Drain blocks unassign until the in-flight task settles.
        expect(mockRdKafka.incrementalUnassign).not.toHaveBeenCalled()
        p1.resolve()
        await delay(20)

        expect(mockRdKafka.incrementalUnassign).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 1 }])
        expect((consumer as any).running).toBe(true)
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

    it('eachBatch throwing: propagates the error and kills the loop (matches v1)', async () => {
        // v2 deliberately does NOT catch eachBatch errors. The loop crashes, connect()'s
        // .catch() re-throws to the orchestrator, the pod restarts, and the batch is
        // re-read from the last committed offset (at-least-once preserved).
        const error = new Error('boom')
        const eachBatch = jest.fn().mockRejectedValue(error)

        // Capture the loop promise so we can assert it rejects with our error.
        await consumer.connect(eachBatch)
        const loopDone = (consumer as any).loopDone as Promise<void>

        registeredRebalanceCb!({ code: CODES.ERRORS.ERR__ASSIGN_PARTITIONS } as any, [
            { topic: 'test-topic', partition: 0 },
        ])
        if (consumeCallback) {
            const cb = consumeCallback
            consumeCallback = undefined
            cb(null, [])
        }
        await delay(5)

        consumeCallback!(null, [createMessage({ offset: 7, partition: 0 })])
        await expect(loopDone).rejects.toBe(error)
        expect(mockRdKafka.offsetsStore).not.toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0, offset: 8 }])
        // afterEach calls disconnect() — the loopDone has already settled, so it's a no-op.
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

    it('backgroundTask rejection: latches fatalError and skips offset store', async () => {
        // Loop-exit propagation is covered by the existing "eachBatch throwing" test plus
        // the runLoop fatalError guard. Here we pin the new behavior: the rejection is
        // latched onto fatalError and offsets for the failed batch are not stored.
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)
        // Suppress unhandled-rejection warning in case the loop ticks (and throws fatalError)
        // during afterEach teardown before disconnect attaches its catch handler.
        ;((consumer as any).loopDone as Promise<void>).catch(() => {})

        const failure = new Error('column "X" does not exist')
        const failing = triggerablePromise<void>()
        eachBatch.mockImplementationOnce(() => Promise.resolve({ backgroundTask: failing.promise }))

        consumeCallback!(null, [createMessage({ offset: 1, partition: 0 })])
        await delay(2)
        failing.reject(failure)
        await delay(10)

        expect(captureException).toHaveBeenCalledWith(failure)
        expect((consumer as any).fatalError).toBe(failure)
        expect(mockRdKafka.offsetsStore).not.toHaveBeenCalled()
    })

    it('backgroundTask rejection: a later successful batch must NOT advance the bookmark past the failed one', async () => {
        // The cross-batch ordering bug: batch N's task fails, batch N+1's succeeds, and
        // without the fatalError gate batch N+1 would store its (higher) offset, silently
        // committing past the lost events.
        ;(consumer as any).maxBackgroundTasks = 4
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)
        ;((consumer as any).loopDone as Promise<void>).catch(() => {})

        const failure = new Error('column "X" does not exist')
        const slowFailure = triggerablePromise<void>()
        eachBatch.mockImplementationOnce(() => Promise.resolve({ backgroundTask: slowFailure.promise }))
        consumeCallback!(null, [createMessage({ offset: 100, partition: 0 })])
        await delay(2)

        // Second batch on the same partition with a successful, fast task.
        eachBatch.mockImplementationOnce(() => Promise.resolve({ backgroundTask: Promise.resolve() }))
        consumeCallback!(null, [createMessage({ offset: 200, partition: 0 })])
        await delay(10)

        // Resolve the first batch's task with a failure AFTER batch N+1 finished its own work.
        slowFailure.reject(failure)
        await delay(20)

        const partition0Stores = (mockRdKafka.offsetsStore as jest.Mock).mock.calls.filter(([offsets]) =>
            offsets.some((o: any) => o.partition === 0)
        )
        expect(partition0Stores).toEqual([])
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

    // === Partition lifecycle callbacks (Stage 1a) ===

    it('onPartitionsAssigned: called with the assigned partitions after incrementalAssign', async () => {
        // Mirrors the revoke ordering snapshot: capture at-callback-time whether
        // incrementalAssign has already fired. This catches a regression where the
        // callback gets reordered to fire BEFORE incrementalAssign — bare
        // toHaveBeenCalledWith on both mocks would silently pass.
        const callbackAssignSnapshot: { wasCalled: boolean }[] = []
        const onPartitionsAssigned = jest.fn().mockImplementation(() => {
            callbackAssignSnapshot.push({
                wasCalled: (mockRdKafka.incrementalAssign as jest.Mock).mock.calls.length > 0,
            })
            return Promise.resolve()
        })
        consumer = new KafkaConsumerV2({
            groupId: 'test-group-assigned',
            topic: 'test-topic',
            onPartitionsAssigned,
        })
        mockRdKafka = jest.mocked((consumer as any).rdKafkaConsumer)

        const eachBatch = jest.fn(() => Promise.resolve({}))
        await consumer.connect(eachBatch)

        registeredRebalanceCb!({ code: CODES.ERRORS.ERR__ASSIGN_PARTITIONS } as any, [
            { topic: 'test-topic', partition: 0 },
        ])
        releaseConsume()
        await delay(5)

        expect(mockRdKafka.incrementalAssign).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0 }])
        expect(onPartitionsAssigned).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0 }])
        // Callback observed incrementalAssign as already-fired — proves ordering.
        expect(callbackAssignSnapshot).toEqual([{ wasCalled: true }])
    })

    it('onPartitionsAssigned: slow callback blocks the next consume()', async () => {
        const callbackGate = triggerablePromise()
        const onPartitionsAssigned = jest.fn().mockImplementation(async () => {
            await callbackGate.promise
        })
        consumer = new KafkaConsumerV2({
            groupId: 'test-group-assigned-slow',
            topic: 'test-topic',
            onPartitionsAssigned,
        })
        mockRdKafka = jest.mocked((consumer as any).rdKafkaConsumer)

        const eachBatch = jest.fn(() => Promise.resolve({}))
        await consumer.connect(eachBatch)

        registeredRebalanceCb!({ code: CODES.ERRORS.ERR__ASSIGN_PARTITIONS } as any, [
            { topic: 'test-topic', partition: 0 },
        ])
        releaseConsume()
        await delay(10)

        expect(onPartitionsAssigned).toHaveBeenCalled()
        // The loop is awaiting the callback inside handleRebalanceEvent — no new consume()
        // call has been made since the IDLE keepalive one.
        const consumeCallsBefore = mockRdKafka.consume.mock.calls.length

        callbackGate.resolve()
        await delay(10)

        expect(mockRdKafka.consume.mock.calls.length).toBeGreaterThan(consumeCallsBefore)
    })

    it('onPartitionsAssigned: throwing callback does not block subsequent consume()', async () => {
        const onPartitionsAssigned = jest.fn().mockRejectedValue(new Error('assign boom'))
        consumer = new KafkaConsumerV2({
            groupId: 'test-group-assigned-throw',
            topic: 'test-topic',
            onPartitionsAssigned,
        })
        mockRdKafka = jest.mocked((consumer as any).rdKafkaConsumer)

        const eachBatch = jest.fn(() => Promise.resolve({}))
        await consumer.connect(eachBatch)

        registeredRebalanceCb!({ code: CODES.ERRORS.ERR__ASSIGN_PARTITIONS } as any, [
            { topic: 'test-topic', partition: 0 },
        ])
        releaseConsume()
        await delay(10)

        expect(onPartitionsAssigned).toHaveBeenCalled()
        expect(captureException).toHaveBeenCalledWith(expect.objectContaining({ message: 'assign boom' }))
        // Loop survives and keeps polling.
        releaseConsume()
        await delay(5)
        expect((consumer as any).running).toBe(true)
    })

    it('onPartitionsRevoked: called after drain and before incrementalUnassign', async () => {
        const callbackUnassignSnapshot: { wasCalled: boolean }[] = []
        const onPartitionsRevoked = jest.fn().mockImplementation(() => {
            callbackUnassignSnapshot.push({
                wasCalled: (mockRdKafka.incrementalUnassign as jest.Mock).mock.calls.length > 0,
            })
            return Promise.resolve()
        })
        consumer = new KafkaConsumerV2({
            groupId: 'test-group-revoked-ordering',
            topic: 'test-topic',
            onPartitionsRevoked,
        })
        mockRdKafka = jest.mocked((consumer as any).rdKafkaConsumer)
        ;(consumer as any).maxBackgroundTasks = 5

        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        const flushPromise = triggerablePromise()
        await dispatchBatch(eachBatch, [createMessage({ offset: 1, partition: 0 })], flushPromise.promise)

        fireRevoke()
        await delay(5)
        // Drain blocked on flushPromise — callback must NOT have fired yet.
        expect(onPartitionsRevoked).not.toHaveBeenCalled()

        flushPromise.resolve()
        await delay(20)

        // When the callback ran, incrementalUnassign had NOT been called yet.
        expect(callbackUnassignSnapshot).toEqual([{ wasCalled: false }])
        // After the callback returned, unassign DID fire.
        expect(mockRdKafka.incrementalUnassign).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0 }])
    })

    it('onPartitionsRevoked: slow callback delays unassign', async () => {
        const callbackGate = triggerablePromise()
        const onPartitionsRevoked = jest.fn().mockImplementation(async () => {
            await callbackGate.promise
        })
        consumer = new KafkaConsumerV2({
            groupId: 'test-group-revoked-slow',
            topic: 'test-topic',
            onPartitionsRevoked,
        })
        mockRdKafka = jest.mocked((consumer as any).rdKafkaConsumer)

        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        fireRevoke()
        await delay(20)

        expect(onPartitionsRevoked).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0 }])
        expect(mockRdKafka.incrementalUnassign).not.toHaveBeenCalled()

        callbackGate.resolve()
        await delay(10)
        expect(mockRdKafka.incrementalUnassign).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0 }])
    })

    it('onPartitionsRevoked: throwing callback does not block unassign', async () => {
        const onPartitionsRevoked = jest.fn().mockRejectedValue(new Error('revoke boom'))
        consumer = new KafkaConsumerV2({
            groupId: 'test-group-revoked-throw',
            topic: 'test-topic',
            onPartitionsRevoked,
        })
        mockRdKafka = jest.mocked((consumer as any).rdKafkaConsumer)

        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        fireRevoke()
        await delay(20)

        expect(onPartitionsRevoked).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0 }])
        expect(mockRdKafka.incrementalUnassign).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0 }])
        expect(captureException).toHaveBeenCalledWith(expect.objectContaining({ message: 'revoke boom' }))
    })

    // === backgroundTask pre-commit contract (Stage 1b) ===

    it('backgroundTask contract: offsetsStore is not called until backgroundTask resolves', async () => {
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        const task = triggerablePromise()
        await dispatchBatch(eachBatch, [createMessage({ offset: 1, partition: 0 })], task.promise)
        await delay(10)

        // backgroundTask still pending — store must not have been called.
        expect(mockRdKafka.offsetsStore).not.toHaveBeenCalled()

        task.resolve()
        await delay(10)

        expect(mockRdKafka.offsetsStore).toHaveBeenCalledWith([{ topic: 'test-topic', partition: 0, offset: 2 }])
    })

    it('backgroundTask contract: rejecting backgroundTask skips offsetsStore', async () => {
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        const task = triggerablePromise()
        // Defensive: attach a no-op handler immediately so the rejection is never
        // briefly-unhandled if the consumer hasn't subscribed yet under CI timing
        // pressure. The consumer's own `.then(_, reject)` inside raceWithTimeout still
        // runs, fires captureException, and skips the offset store.
        task.promise.catch(() => {})
        await dispatchBatch(eachBatch, [createMessage({ offset: 1, partition: 0 })], task.promise)
        await delay(2)

        task.reject(new Error('flush failed'))
        await delay(10)

        expect(mockRdKafka.offsetsStore).not.toHaveBeenCalled()
        expect(captureException).toHaveBeenCalledWith(expect.objectContaining({ message: 'flush failed' }))
    })

    it('backgroundTask contract: backgroundTask exceeding backgroundTaskTimeoutMs skips offsetsStore', async () => {
        // Force a short timeout so we don't wait the default 60s for the race to fire.
        ;(consumer as any).backgroundTaskTimeoutMs = 30
        const eachBatch = jest.fn(() => Promise.resolve({}))
        await startConsuming(eachBatch)

        // Never resolves — guaranteed to trip backgroundTaskTimeoutMs.
        const stuck = triggerablePromise()
        // Defensive no-op handler (see the rejecting test for the rationale).
        stuck.promise.catch(() => {})
        await dispatchBatch(eachBatch, [createMessage({ offset: 1, partition: 0 })], stuck.promise)

        // Wait past the timeout.
        await delay(60)

        expect(mockRdKafka.offsetsStore).not.toHaveBeenCalled()
        expect(captureException).toHaveBeenCalledWith(
            expect.objectContaining({ message: expect.stringMatching(/background_task_timeout_after_30ms/) })
        )

        // Resolve the gate so afterEach can clean up.
        stuck.resolve()
    })
})

afterAll(() => {
    // Belt and braces — make sure no tracked promises leak between files.
    while (activePromiseResolvers.length > 0) {
        activePromiseResolvers[0]()
    }
})
