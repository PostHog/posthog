import { BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { createOkContext } from './helpers'
import { InterleavingBatchPipeline, InterleavingCallbacks, PullOutcome } from './interleaving-batch-pipeline'

type Ctx = Record<string, never>
type Batch = BatchPipelineResultWithContext<string, Ctx>

function batch(value: string): Batch {
    return [createOkContext<string, Ctx>(value, {})]
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: unknown) => void } {
    let resolve!: (value: T) => void
    let reject!: (error: unknown) => void
    const promise = new Promise<T>((res, rej) => {
        resolve = res
        reject = rej
    })
    return { promise, resolve, reject }
}

describe('InterleavingBatchPipeline', () => {
    const tick = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))

    function build(
        callbacks: Partial<InterleavingCallbacks<string, string, Ctx, Ctx, never>>
    ): InterleavingBatchPipeline<string, string, Ctx, Ctx, never> {
        return new InterleavingBatchPipeline<string, string, Ctx, Ctx, never>({
            onFeed: callbacks.onFeed ?? jest.fn(),
            onSourcePull:
                callbacks.onSourcePull ??
                jest.fn().mockResolvedValue({ kind: 'drained' } as PullOutcome<string, Ctx, never>),
            onProcessPull: callbacks.onProcessPull ?? jest.fn().mockResolvedValue(null),
        })
    }

    it('emits a passthrough batch without draining the subpipeline', async () => {
        const passthrough = batch('passthrough')
        const onProcessPull = jest.fn()
        const pipeline = build({
            onSourcePull: jest.fn().mockResolvedValue({ kind: 'emit', batch: passthrough }),
            onProcessPull,
        })

        expect(await pipeline.next()).toBe(passthrough)
        expect(onProcessPull).not.toHaveBeenCalled()
    })

    it('drains the subpipeline when input was routed into it', async () => {
        const drained = batch('drained')
        const pipeline = build({
            onSourcePull: jest.fn().mockResolvedValue({ kind: 'drain' }),
            onProcessPull: jest.fn().mockResolvedValue(drained),
        })

        expect(await pipeline.next()).toBe(drained)
    })

    it('returns null when the source is drained and the subpipeline is empty', async () => {
        const pipeline = build({
            onSourcePull: jest.fn().mockResolvedValue({ kind: 'drained' }),
            onProcessPull: jest.fn().mockResolvedValue(null),
        })

        expect(await pipeline.next()).toBeNull()
    })

    it('keeps pulling while the source still has batches even if the sub yields nothing', async () => {
        const onSourcePull = jest
            .fn()
            .mockResolvedValueOnce({ kind: 'drain' })
            .mockResolvedValueOnce({ kind: 'drained' })
        const pipeline = build({ onSourcePull, onProcessPull: jest.fn().mockResolvedValue(null) })

        expect(await pipeline.next()).toBeNull()
        expect(onSourcePull).toHaveBeenCalledTimes(2)
    })

    it('forwards feed() elements to onFeed', () => {
        const onFeed = jest.fn()
        const pipeline = build({ onFeed })
        const elements = [createOkContext<string, Ctx>('x', {})]

        pipeline.feed(elements)

        expect(onFeed).toHaveBeenCalledWith(elements)
    })

    it('wakes a next() parked on a slow sub and does not re-issue the sub pull', async () => {
        // The sub stays parked forever; only a feed() should unblock next().
        const neverResolves = deferred<Batch | null>()
        const onProcessPull = jest.fn().mockReturnValue(neverResolves.promise)
        const afterFeed = batch('after-feed')
        const onSourcePull = jest
            .fn()
            .mockResolvedValueOnce({ kind: 'drain' })
            .mockResolvedValueOnce({ kind: 'emit', batch: afterFeed })
        const onFeed = jest.fn()
        const pipeline = build({ onFeed, onSourcePull, onProcessPull })

        let settled = false
        const nextPromise = pipeline.next().then((result) => {
            settled = true
            return result
        })

        await tick()
        expect(settled).toBe(false) // parked on the slow sub

        pipeline.feed([createOkContext<string, Ctx>('y', {})])
        const result = await nextPromise

        expect(result).toBe(afterFeed)
        expect(onFeed).toHaveBeenCalledTimes(1)
        expect(onSourcePull).toHaveBeenCalledTimes(2)
        // Memoized: the feed-driven loop must re-await the same pending sub pull,
        // not start a second concurrent one.
        expect(onProcessPull).toHaveBeenCalledTimes(1)
    })

    it('propagates a sub error, then re-issues the sub pull on the next call', async () => {
        // A poisoned sub can still hand out remaining completed batches before it
        // re-rejects, so a throw must clear the memoized pull.
        const remaining = batch('remaining')
        const onProcessPull = jest.fn().mockRejectedValueOnce(new Error('poisoned')).mockResolvedValueOnce(remaining)
        const pipeline = build({ onSourcePull: jest.fn().mockResolvedValue({ kind: 'drain' }), onProcessPull })

        await expect(pipeline.next()).rejects.toThrow('poisoned')
        expect(await pipeline.next()).toBe(remaining)
        expect(onProcessPull).toHaveBeenCalledTimes(2)
    })
})
