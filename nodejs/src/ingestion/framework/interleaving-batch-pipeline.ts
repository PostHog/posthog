import { ChunkPipeline, ChunkPipelineResultWithContext, OkResultWithContext } from './chunk-pipeline.interface'
import { ResettableSignal } from './resettable-signal'

/**
 * What {@link InterleavingCallbacks.onSourcePull} reports after pulling one
 * batch from the upstream pipeline:
 * - `emit`: return this batch to the caller now (e.g. passthrough / non-OK results)
 * - `drain`: input was routed into the subpipeline; drain it for results
 * - `drained`: the upstream pipeline is currently empty
 */
export type PullOutcome<TOutput, COutput, R extends string> =
    | { kind: 'emit'; batch: ChunkPipelineResultWithContext<TOutput, COutput, R> }
    | { kind: 'drain' }
    | { kind: 'drained' }

/**
 * The stage-specific behavior injected into an {@link InterleavingBatchPipeline},
 * leaving the pipeline itself to own only the synchronization.
 */
export interface InterleavingCallbacks<TInput, TOutput, CInput, COutput, R extends string> {
    /** Deliver feed() elements into the source pipeline (the wake-up is added on top). */
    onFeed: (elements: OkResultWithContext<TInput, CInput>[]) => void
    /**
     * Pull one batch from the source pipeline, route OK results into the
     * processing subpipeline, and report whether to emit immediately, drain the
     * sub, or that the source is empty. Pulled fresh every iteration (no
     * "drained" flag) so a feed that lands after an earlier empty read is always
     * picked up on the next loop.
     */
    onSourcePull: () => Promise<PullOutcome<TOutput, COutput, R>>
    /** Pull the next batch from the processing subpipeline — raced against feeds. */
    onProcessPull: () => Promise<ChunkPipelineResultWithContext<TOutput, COutput, R> | null>
}

/**
 * Generic synchronization for a batch pipeline stage that pulls from an upstream
 * pipeline and feeds a downstream subpipeline which may park on slow in-flight
 * work. `next()` interleaves "pull upstream + route into sub" with "drain sub",
 * racing the drain against a `feed()` wake-up so a later-fed batch is never
 * stranded upstream while the sub is parked (head-of-line avoidance).
 *
 * The stage-specific behavior is injected via {@link InterleavingCallbacks}.
 * See `FilterMapBatchPipeline` for the canonical wiring; the same shape fits any
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
export class InterleavingBatchPipeline<TInput, TOutput, CInput, COutput, R extends string = never>
    implements ChunkPipeline<TInput, TOutput, CInput, COutput, R>
{
    private newInputSignal = new ResettableSignal()
    // Memoized across iterations and across next() calls: the subpipeline is not
    // safe for concurrent callers, so a feed waking us mid-drain must re-await
    // the same pending next() rather than issue a second one.
    private subPending: Promise<ChunkPipelineResultWithContext<TOutput, COutput, R> | null> | null = null
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
            // Arm a fresh wake-up before pulling. A feed landing during the pull
            // is still seen by the race below (not lost), while a stale signal
            // from an already-consumed feed does NOT over-eagerly pull the next
            // batch into an in-flight subpipeline (which would coalesce batches
            // that downstream stages like gather() expect to stay separate).
            this.newInputSignal.reset()

            let pulled: PullOutcome<TOutput, COutput, R>
            try {
                pulled = await this.callbacks.onSourcePull()
            } catch (error) {
                // Source failed: latch and switch to draining the sub before
                // rejecting, so any already in-flight results still come out.
                this.failure = { error }
                return this.drainThenReject()
            }
            if (pulled.kind === 'emit') {
                return pulled.batch
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
