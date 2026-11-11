import { ChunkPipelineResultWithContext } from './chunk-pipeline.interface'
import { createOkContext } from './helpers'
import { InterleavingCallbacks, InterleavingChunkPipeline, PullOutcome } from './interleaving-chunk-pipeline'

type Ctx = Record<string, never>
type Chunk = ChunkPipelineResultWithContext<string, Ctx>

function chunk(value: string): Chunk {
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

describe('InterleavingChunkPipeline', () => {
    const tick = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))

    function build(
        callbacks: Partial<InterleavingCallbacks<string, string, Ctx, Ctx, never>>
    ): InterleavingChunkPipeline<string, string, Ctx, Ctx, never> {
        return new InterleavingChunkPipeline<string, string, Ctx, Ctx, never>({
            onFeed: callbacks.onFeed ?? jest.fn(),
            onSourcePull:
                callbacks.onSourcePull ??
                jest.fn().mockResolvedValue({ kind: 'drained' } as PullOutcome<string, Ctx, never>),
            onProcessPull: callbacks.onProcessPull ?? jest.fn().mockResolvedValue(null),
        })
    }

    it('emits a passthrough chunk without draining the subpipeline', async () => {
        const passthrough = chunk('passthrough')
        const onProcessPull = jest.fn()
        const pipeline = build({
            onSourcePull: jest.fn().mockResolvedValue({ kind: 'emit', chunk: passthrough }),
            onProcessPull,
        })

        expect(await pipeline.next()).toBe(passthrough)
        expect(onProcessPull).not.toHaveBeenCalled()
    })

    it('drains the subpipeline when input was routed into it', async () => {
        const drained = chunk('drained')
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

    it('keeps pulling while the source still has chunks even if the sub yields nothing', async () => {
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
        const neverResolves = deferred<Chunk | null>()
        const onProcessPull = jest.fn().mockReturnValue(neverResolves.promise)
        const afterFeed = chunk('after-feed')
        const onSourcePull = jest
            .fn()
            .mockResolvedValueOnce({ kind: 'drain' })
            .mockResolvedValueOnce({ kind: 'emit', chunk: afterFeed })
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

    it('poisons after a sub error, draining remaining in-flight results first', async () => {
        // The sub surfaces the error, then can still hand out work that was already
        // in flight; once it is exhausted the stage rejects permanently.
        const remaining = chunk('remaining')
        const onSourcePull = jest.fn().mockResolvedValue({ kind: 'drain' })
        const onProcessPull = jest
            .fn()
            .mockRejectedValueOnce(new Error('poisoned'))
            .mockResolvedValueOnce(remaining)
            .mockResolvedValue(null)
        const pipeline = build({ onSourcePull, onProcessPull })

        await expect(pipeline.next()).rejects.toThrow('poisoned') // first surfacing
        expect(await pipeline.next()).toBe(remaining) // drained in-flight result
        await expect(pipeline.next()).rejects.toThrow('poisoned') // then poisoned
        await expect(pipeline.next()).rejects.toThrow('poisoned') // permanently
        expect(onSourcePull).toHaveBeenCalledTimes(1) // no source pulls after poison
        expect(onProcessPull).toHaveBeenCalledTimes(4)
    })

    it('reuses the in-flight sub pull across a feed wake and returns its eventual value', async () => {
        // The sub pull issued before the feed must be the same one that later
        // resolves the value — a feed-driven loop must not start a second pull.
        const slowSub = deferred<Chunk | null>()
        const onProcessPull = jest.fn().mockReturnValue(slowSub.promise)
        const onSourcePull = jest.fn().mockResolvedValue({ kind: 'drain' })
        const pipeline = build({ onSourcePull, onProcessPull })

        let settled = false
        const nextPromise = pipeline.next().then((result) => {
            settled = true
            return result
        })

        await tick()
        expect(settled).toBe(false)

        pipeline.feed([createOkContext<string, Ctx>('y', {})])
        await tick()
        expect(settled).toBe(false) // looped back, still parked on the same sub pull

        const eventual = chunk('eventual')
        slowSub.resolve(eventual)

        expect(await nextPromise).toBe(eventual)
        expect(onProcessPull).toHaveBeenCalledTimes(1)
        expect(onSourcePull).toHaveBeenCalledTimes(2)
    })

    it('preserves an in-flight sub pull across an emit so the next call reuses it', async () => {
        // A feed wakes the parked sub, the looped iteration returns via emit, but
        // the sub pull is still in flight — the next call must reuse it, not start a new one.
        const neverResolves = deferred<Chunk | null>()
        const onProcessPull = jest.fn().mockReturnValue(neverResolves.promise)
        const afterFeed = chunk('after-feed')
        const onSourcePull = jest
            .fn()
            .mockResolvedValueOnce({ kind: 'drain' })
            .mockResolvedValueOnce({ kind: 'emit', chunk: afterFeed })
            .mockResolvedValue({ kind: 'drain' })
        const pipeline = build({ onSourcePull, onProcessPull })

        const nextPromise = pipeline.next()
        await tick()

        pipeline.feed([createOkContext<string, Ctx>('y', {})])
        expect(await nextPromise).toBe(afterFeed)
        expect(onProcessPull).toHaveBeenCalledTimes(1)

        let settled = false
        void pipeline.next().then(() => {
            settled = true
        })
        await tick()
        expect(settled).toBe(false) // reused the still-in-flight sub pull
        expect(onProcessPull).toHaveBeenCalledTimes(1)
    })

    it('coalesces multiple feeds during a single park into one wake', async () => {
        // Both feeds resolve the same one-shot signal, so the parked next() wakes
        // once and re-pulls the source once — it does not loop per feed.
        const slowSub = deferred<Chunk | null>()
        const onProcessPull = jest.fn().mockReturnValue(slowSub.promise)
        const onSourcePull = jest.fn().mockResolvedValue({ kind: 'drain' })
        const onFeed = jest.fn()
        const pipeline = build({ onFeed, onSourcePull, onProcessPull })

        const nextPromise = pipeline.next()
        await tick()

        pipeline.feed([createOkContext<string, Ctx>('y', {})])
        pipeline.feed([createOkContext<string, Ctx>('z', {})])
        await tick()

        expect(onFeed).toHaveBeenCalledTimes(2)
        expect(onSourcePull).toHaveBeenCalledTimes(2)
        expect(onProcessPull).toHaveBeenCalledTimes(1)

        const eventual = chunk('eventual')
        slowSub.resolve(eventual)
        expect(await nextPromise).toBe(eventual)
    })

    it('does not over-eagerly re-pull the source from a stale already-consumed feed signal', async () => {
        // A feed with no parked next() leaves the one-shot signal resolved. The
        // reset at the top of next() discards it, so the loop parks on the slow
        // sub instead of letting the stale signal win the race and re-pull the
        // source (which would coalesce chunks downstream stages keep separate).
        const slowSub = deferred<Chunk | null>()
        const onProcessPull = jest.fn().mockReturnValue(slowSub.promise)
        const onSourcePull = jest.fn().mockResolvedValue({ kind: 'drain' })
        const pipeline = build({ onSourcePull, onProcessPull })

        pipeline.feed([createOkContext<string, Ctx>('y', {})])

        const nextPromise = pipeline.next()
        await tick()
        expect(onSourcePull).toHaveBeenCalledTimes(1)

        const chunk1 = chunk('chunk1')
        slowSub.resolve(chunk1)
        expect(await nextPromise).toBe(chunk1)
        expect(onSourcePull).toHaveBeenCalledTimes(1)
    })

    it('poisons after a source error, draining in-flight sub results first', async () => {
        const remaining = chunk('remaining')
        const onSourcePull = jest
            .fn()
            .mockRejectedValueOnce(new Error('source boom'))
            .mockResolvedValue({ kind: 'drain' })
        const onProcessPull = jest.fn().mockResolvedValueOnce(remaining).mockResolvedValue(null)
        const pipeline = build({ onSourcePull, onProcessPull })

        expect(await pipeline.next()).toBe(remaining) // source failed, but in-flight sub result drains first
        await expect(pipeline.next()).rejects.toThrow('source boom')
        await expect(pipeline.next()).rejects.toThrow('source boom') // permanently
        expect(onSourcePull).toHaveBeenCalledTimes(1) // no source pulls after poison
    })

    it('rejects immediately on a source error when nothing is in flight', async () => {
        const onSourcePull = jest.fn().mockRejectedValue(new Error('source boom'))
        const onProcessPull = jest.fn().mockResolvedValue(null)
        const pipeline = build({ onSourcePull, onProcessPull })

        await expect(pipeline.next()).rejects.toThrow('source boom')
        await expect(pipeline.next()).rejects.toThrow('source boom')
    })

    it('picks up a feed that lands during the source pull and re-pulls, reusing the sub', async () => {
        // The feed arrives while the first source pull is still in flight. The
        // fresh signal armed before the pull must capture it so the loop re-pulls
        // instead of committing to the first pull's (now stale) outcome.
        const slowSource = deferred<PullOutcome<string, Ctx, never>>()
        const onSourcePull = jest.fn().mockReturnValueOnce(slowSource.promise).mockResolvedValue({ kind: 'drained' })
        const slowSub = deferred<Chunk | null>()
        const onProcessPull = jest.fn().mockReturnValue(slowSub.promise)
        const pipeline = build({ onSourcePull, onProcessPull })

        let settled = false
        const nextPromise = pipeline.next().then((result) => {
            settled = true
            return result
        })
        await tick()
        expect(settled).toBe(false) // parked on the slow source pull

        pipeline.feed([createOkContext<string, Ctx>('y', {})])
        slowSource.resolve({ kind: 'drain' })
        await tick()

        expect(onSourcePull).toHaveBeenCalledTimes(2) // the in-flight feed forced a re-pull
        expect(onProcessPull).toHaveBeenCalledTimes(1) // the sub pull was reused
        expect(settled).toBe(false)

        const eventual = chunk('eventual')
        slowSub.resolve(eventual)
        expect(await nextPromise).toBe(eventual)
    })

    it('handles repeated feeds across separate parks without re-issuing the sub pull', async () => {
        const slowSub = deferred<Chunk | null>()
        const onProcessPull = jest.fn().mockReturnValue(slowSub.promise)
        const onSourcePull = jest.fn().mockResolvedValue({ kind: 'drain' })
        const pipeline = build({ onSourcePull, onProcessPull })

        const nextPromise = pipeline.next()
        await tick()

        // Two feeds, each landing in its own park (a tick apart), wake the loop
        // separately — so each re-pulls the source once.
        pipeline.feed([createOkContext<string, Ctx>('y', {})])
        await tick()
        pipeline.feed([createOkContext<string, Ctx>('z', {})])
        await tick()

        expect(onSourcePull).toHaveBeenCalledTimes(3)
        expect(onProcessPull).toHaveBeenCalledTimes(1)

        const eventual = chunk('eventual')
        slowSub.resolve(eventual)
        expect(await nextPromise).toBe(eventual)
    })
})
