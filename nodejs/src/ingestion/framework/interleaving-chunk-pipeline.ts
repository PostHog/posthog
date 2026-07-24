import { ChunkPipeline, ChunkPipelineResultWithContext, OkResultWithContext } from './chunk-pipeline.interface'
import { ResettableSignal } from './resettable-signal'

/**
 * What {@link InterleavingCallbacks.onSourcePull} reports after pulling one
 * chunk from the upstream pipeline:
 * - `emit`: return this chunk to the caller now (e.g. passthrough / non-OK results)
 * - `drain`: input was routed into the subpipeline; drain it for results
 * - `drained`: the upstream pipeline is currently empty
 */
export type PullOutcome<TOutput, COutput, R extends string> =
    | { kind: 'emit'; chunk: ChunkPipelineResultWithContext<TOutput, COutput, R> }
    | { kind: 'drain' }
    | { kind: 'drained' }

/**
 * The stage-specific behavior injected into an {@link InterleavingChunkPipeline},
 * leaving the pipeline itself to own only the synchronization.
 */
export interface InterleavingCallbacks<TInput, TOutput, CInput, COutput, R extends string> {
    /** Deliver feed() elements into the source pipeline (the wake-up is added on top). */
    onFeed: (elements: OkResultWithContext<TInput, CInput>[]) => void
    /**
     * Pull one chunk from the source pipeline, route OK results into the
     * processing subpipeline, and report whether to emit immediately, drain the
     * sub, or that the source is empty. Pulled fresh every iteration (no
     * "drained" flag) so a feed that lands after an earlier empty read is always
     * picked up on the next loop.
     */
    onSourcePull: () => Promise<PullOutcome<TOutput, COutput, R>>
    /**
     * Pull the next chunk from the processing subpipeline — raced against feeds
     * and against in-flight source pulls. May be issued speculatively before or
     * concurrently with source routing, so implementations must tolerate pulls
     * on an empty sub (return null promptly) and must not treat a null that
     * races a concurrent routing as corruption (guard with an epoch — see
     * FanOutFanInChunkPipeline's fanOutEpoch).
     */
    onProcessPull: () => Promise<ChunkPipelineResultWithContext<TOutput, COutput, R> | null>
}

/**
 * Generic synchronization for a chunk pipeline stage that pulls from an upstream
 * pipeline and feeds a downstream subpipeline which may park on slow in-flight
 * work. `next()` interleaves "pull upstream + route into sub" with "drain sub",
 * racing the drain against a `feed()` wake-up so a later-fed chunk is never
 * stranded upstream while the sub is parked (head-of-line avoidance).
 *
 * The stage-specific behavior is injected via {@link InterleavingCallbacks}.
 * See `FilterMapChunkPipeline` for the canonical wiring; the same shape fits any
 * pull-from-prev / feed-sub / drain-sub stage.
 *
 * Failures poison the whole stage. The first error from either callback (the
 * source pull or the sub drain) is latched: from then on `next()` issues no new
 * source pulls, drains whatever was already in flight in the sub, and once that
 * is exhausted rejects with the original error — permanently. This mirrors the
 * grouping stage's processor-failure handling (drain what completed, then wedge)
 * and gives callers a consistent terminal rejection instead of partial recovery.
 *
 * @remarks `next()` must not be called concurrently — `subPending` is shared
 * mutable state, so two overlapping calls would issue duplicate `onProcessPull`
 * pulls and tear it. Callers serialize externally (e.g. `BatchingPipeline`'s
 * pump mutex); `feed()` is safe to call concurrently with `next()`.
 */
export class InterleavingChunkPipeline<TInput, TOutput, CInput, COutput, R extends string = never>
    implements ChunkPipeline<TInput, TOutput, CInput, COutput, R>
{
    private newInputSignal = new ResettableSignal()
    // Memoized across iterations and across next() calls: the subpipeline is not
    // safe for concurrent callers, so a feed waking us mid-drain must re-await
    // the same pending next() rather than issue a second one.
    private subPending: Promise<ChunkPipelineResultWithContext<TOutput, COutput, R> | null> | null = null
    // Memoized like subPending, for the same reason: a source pull that parks on
    // slow in-flight upstream work (e.g. a bounded gather awaiting a carried
    // pull) is raced against the sub and carried across next() calls, so
    // completed sub results are never stranded behind it and no duplicate
    // source pull is ever issued.
    private sourcePending: Promise<PullOutcome<TOutput, COutput, R>> | null = null
    // The first error seen from either callback. Once set, the stage is poisoned:
    // no more source pulls, drain the sub dry, then reject with this forever.
    private failure: { error: unknown } | null = null

    constructor(private callbacks: InterleavingCallbacks<TInput, TOutput, CInput, COutput, R>) {}

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.callbacks.onFeed(elements)
        // Wake a next() parked on the subpipeline so it loops back and pulls the
        // freshly delivered upstream input.
        this.newInputSignal.resolve()
    }

    async next(): Promise<ChunkPipelineResultWithContext<TOutput, COutput, R> | null> {
        // Once poisoned, stop pulling new input: drain what is still in flight in
        // the sub, then reject permanently with the original error.
        if (this.failure) {
            return this.drainThenReject()
        }

        while (true) {
            // Obtain one source outcome — racing the (memoized) pull against the
            // sub, so completed sub results are handed out instead of being
            // stranded behind a source pull parked on slow in-flight work.
            let pulled: PullOutcome<TOutput, COutput, R> | undefined
            // Once the sub reports empty it stays empty until the source routes
            // more input, so don't re-pull it while waiting on the source (that
            // would spin on instantly-resolving nulls).
            let subSawNull = false
            while (pulled === undefined) {
                if (!this.sourcePending) {
                    // Arm a fresh wake-up before pulling. A feed landing during
                    // the pull is still seen by the drain race below (not
                    // lost), while a stale signal from an already-consumed feed
                    // does NOT over-eagerly pull the next chunk into an
                    // in-flight subpipeline (which would coalesce chunks that
                    // downstream stages like gather() expect to stay separate).
                    this.newInputSignal.reset()
                    this.sourcePending = this.callbacks.onSourcePull()
                }
                if (!this.subPending && !subSawNull) {
                    this.subPending = this.callbacks.onProcessPull()
                }

                if (!this.subPending) {
                    try {
                        pulled = await this.sourcePending
                    } catch (error) {
                        // Source failed: latch and switch to draining the sub
                        // before rejecting, so any already in-flight results
                        // still come out.
                        this.sourcePending = null
                        this.failure = { error }
                        return this.drainThenReject()
                    }
                    this.sourcePending = null
                    break
                }

                const raced = await Promise.race([
                    this.sourcePending.then(
                        (outcome) => ({ kind: 'source' as const, outcome }),
                        (error: unknown) => ({ kind: 'source-error' as const, error })
                    ),
                    this.subPending.then(
                        (result) => ({ kind: 'sub' as const, result }),
                        (error: unknown) => ({ kind: 'sub-error' as const, error })
                    ),
                ])
                if (raced.kind === 'source') {
                    this.sourcePending = null
                    pulled = raced.outcome
                } else if (raced.kind === 'source-error') {
                    this.sourcePending = null
                    this.failure = { error: raced.error }
                    return this.drainThenReject()
                } else if (raced.kind === 'sub-error') {
                    this.subPending = null
                    this.failure = { error: raced.error }
                    throw raced.error
                } else {
                    this.subPending = null
                    if (raced.result !== null) {
                        // Completed sub results go out now; the source pull
                        // stays in flight and carries over to the next call.
                        return raced.result
                    }
                    subSawNull = true
                }
            }

            if (pulled.kind === 'emit') {
                return pulled.chunk
            }

            // Drain the subpipeline, racing against a concurrent feed: if the sub
            // is parked on slow in-flight work, a feed() landing now wakes us to
            // loop back and route the freshly delivered upstream input into it.
            if (!this.subPending) {
                this.subPending = this.callbacks.onProcessPull()
            }
            // Tag a rejection as a value so that when the signal wins the race
            // instead, the sub branch is not an unhandled rejection.
            const winner = await Promise.race([
                this.subPending.then(
                    (result) => ({ source: 'sub' as const, result }),
                    (error: unknown) => ({ source: 'sub-error' as const, error })
                ),
                this.newInputSignal.wait().then(() => ({ source: 'signal' as const })),
            ])

            if (winner.source === 'signal') {
                continue
            }

            this.subPending = null
            if (winner.source === 'sub-error') {
                // Surface the sub failure now and latch it; later calls drain any
                // remaining in-flight results, then reject permanently.
                this.failure = { error: winner.error }
                throw winner.error
            }
            if (winner.result !== null) {
                return winner.result
            }
            // Subpipeline drained. If upstream was also empty this iteration, the
            // whole stage is drained; otherwise loop to pull and drain more.
            if (pulled.kind === 'drained') {
                return null
            }
        }
    }

    /**
     * Poisoned drain: pull the sub for any work still in flight and emit it, but
     * issue no new source pulls. When the sub is exhausted (null) or re-throws,
     * reject with the latched failure — permanently, since `failure` stays set.
     */
    private async drainThenReject(): Promise<ChunkPipelineResultWithContext<TOutput, COutput, R> | null> {
        if (!this.subPending) {
            this.subPending = this.callbacks.onProcessPull()
        }
        try {
            const result = await this.subPending
            this.subPending = null
            if (result !== null) {
                return result
            }
        } catch {
            // The sub re-threw: it has nothing left to hand out.
            this.subPending = null
        }
        throw this.failure!.error
    }
}
