import { Message } from 'node-rdkafka'

import { delay } from '../utils/utils'
import { SessionRecordingIngester } from './consumer'

/**
 * Unit tests for the post-batch flush contract on SessionRecordingIngester.
 *
 * These tests bypass the heavy constructor by stubbing the ingester instance directly
 * (via `Object.create(prototype)`) and assigning only the fields the methods under test
 * actually read. This isolates the orchestration logic in `processBatchMessages` /
 * `handleEachBatch` from the rest of the system (postgres, redis, S3, encryption …) and
 * lets us assert the backgroundTask contract that Stage 3 will hand to KafkaConsumerV2.
 */

const createMessage = (overrides: Partial<Message> = {}): Message => ({
    value: Buffer.from('test-value'),
    key: Buffer.from('test-key'),
    offset: 1,
    partition: 0,
    topic: 'test-topic',
    size: 10,
    ...overrides,
})

const triggerablePromise = <T = void>(): { promise: Promise<T>; resolve: (value?: T) => void } => {
    let resolveFn: (value?: T) => void = () => {}
    const promise = new Promise<T>((resolve) => {
        resolveFn = (value?: T) => resolve(value as T)
    })
    return { promise, resolve: resolveFn }
}

const makeIngesterStub = (overrides: {
    shouldFlush: boolean | jest.Mock
    flushImpl?: () => Promise<void>
}): {
    ingester: SessionRecordingIngester
    mocks: {
        sessionBatchManager: { shouldFlush: jest.Mock; flush: jest.Mock }
        kafkaConsumer: { heartbeat: jest.Mock; assignments: jest.Mock }
        sessionReplayPipeline: { feed: jest.Mock; next: jest.Mock }
    }
} => {
    const mocks = {
        sessionBatchManager: {
            shouldFlush:
                typeof overrides.shouldFlush === 'function'
                    ? overrides.shouldFlush
                    : jest.fn().mockReturnValue(overrides.shouldFlush),
            flush: jest.fn().mockImplementation(overrides.flushImpl ?? (() => Promise.resolve())),
        },
        kafkaConsumer: {
            heartbeat: jest.fn(),
            assignments: jest.fn().mockReturnValue([]),
        },
        sessionReplayPipeline: {
            feed: jest.fn(),
            // `runSessionReplayPipeline` loops on next() until null; first call ends the loop.
            next: jest.fn().mockResolvedValue(null),
        },
    }

    const ingester = Object.create(SessionRecordingIngester.prototype) as SessionRecordingIngester
    Object.assign(ingester, {
        sessionBatchManager: mocks.sessionBatchManager,
        kafkaConsumer: mocks.kafkaConsumer,
        sessionReplayPipeline: mocks.sessionReplayPipeline,
    })

    return { ingester, mocks }
}

describe('SessionRecordingIngester.processBatchMessages', () => {
    it('returns { backgroundTask } when shouldFlush is true', async () => {
        const { ingester, mocks } = makeIngesterStub({ shouldFlush: true })

        const result = await (ingester as any).processBatchMessages([createMessage()])

        expect(result).toBeDefined()
        expect(result.backgroundTask).toBeInstanceOf(Promise)
        expect(mocks.sessionBatchManager.flush).toHaveBeenCalledTimes(1)
    })

    it('returns undefined and does not call flush when shouldFlush is false', async () => {
        const { ingester, mocks } = makeIngesterStub({ shouldFlush: false })

        const result = await (ingester as any).processBatchMessages([createMessage()])

        expect(result).toBeUndefined()
        expect(mocks.sessionBatchManager.flush).not.toHaveBeenCalled()
    })

    it('runs the pipeline before checking shouldFlush', async () => {
        const callOrder: string[] = []
        const shouldFlush = jest.fn(() => {
            callOrder.push('shouldFlush')
            return false
        })
        const { ingester, mocks } = makeIngesterStub({ shouldFlush })
        mocks.sessionReplayPipeline.feed = jest.fn(() => {
            callOrder.push('feed')
        })

        await (ingester as any).processBatchMessages([createMessage()])

        expect(callOrder).toEqual(['feed', 'shouldFlush'])
    })

    it('returns the flush promise without awaiting it — caller controls when to await', async () => {
        const flushGate = triggerablePromise()
        const { ingester } = makeIngesterStub({
            shouldFlush: true,
            flushImpl: () => flushGate.promise,
        })

        const result = await (ingester as any).processBatchMessages([createMessage()])

        // The flush is in flight but processBatchMessages already returned.
        let resolved = false
        void result.backgroundTask.then(() => {
            resolved = true
        })
        await delay(5)
        expect(resolved).toBe(false)

        flushGate.resolve()
        await result.backgroundTask
        expect(resolved).toBe(true)
    })
})

describe('SessionRecordingIngester.handleEachBatch', () => {
    it('returns { backgroundTask } without awaiting it — the consumer owns the await + commit gating', async () => {
        const flushGate = triggerablePromise()
        const { ingester, mocks } = makeIngesterStub({
            shouldFlush: true,
            flushImpl: () => flushGate.promise,
        })

        const returnValue = await ingester.handleEachBatch([createMessage()])

        // The flush was kicked off but is NOT awaited by handleEachBatch.
        expect(mocks.sessionBatchManager.flush).toHaveBeenCalledTimes(1)
        expect(returnValue).toBeDefined()
        expect(returnValue?.backgroundTask).toBeInstanceOf(Promise)

        // Prove handleEachBatch did not block on the flush: it resolved while the
        // flush gate is still closed.
        let flushTaskResolved = false
        void returnValue!.backgroundTask!.then(() => {
            flushTaskResolved = true
        })
        await delay(5)
        expect(flushTaskResolved).toBe(false)

        flushGate.resolve()
        await returnValue!.backgroundTask
        expect(flushTaskResolved).toBe(true)
    })

    it('returns undefined when no flush was needed', async () => {
        const { ingester, mocks } = makeIngesterStub({ shouldFlush: false })

        const returnValue = await ingester.handleEachBatch([createMessage()])

        expect(returnValue).toBeUndefined()
        expect(mocks.sessionBatchManager.flush).not.toHaveBeenCalled()
    })
})
