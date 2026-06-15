import { BatchPipeline, BatchPipelineResultWithContext, OkResultWithContext } from './batch-pipeline.interface'
import { resettableSignal } from './resettable-signal'

/**
 * What {@link InterleavingCallbacks.onSourcePull} reports after pulling one
 * batch from the upstream pipeline:
 * - `emit`: return this batch to the caller now (e.g. passthrough / non-OK results)
 * - `drain`: input was routed into the subpipeline; drain it for results
 * - `drained`: the upstream pipeline is currently empty
 */
export type PullOutcome<TOutput, COutput, R extends string> =
    | { kind: 'emit'; batch: BatchPipelineResultWithContext<TOutput, COutput, R> }
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
    onProcessPull: () => Promise<BatchPipelineResultWithContext<TOutput, COutput, R> | null>
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
 * @remarks `next()` must not be called concurrently — `subPending` is shared
 * mutable state, so two overlapping calls would issue duplicate `onProcessPull`
 * pulls and tear it. Callers serialize externally (e.g. `BatchingPipeline`'s
 * pump mutex); `feed()` is safe to call concurrently with `next()`.
 */
export class InterleavingBatchPipeline<TInput, TOutput, CInput, COutput, R extends string = never>
    implements BatchPipeline<TInput, TOutput, CInput, COutput, R>
{
    private newInputSignal = resettableSignal()
    // Memoized across iterations and across next() calls: the subpipeline is not
    // safe for concurrent callers, so a feed waking us mid-drain must re-await
    // the same pending next() rather than issue a second one.
    private subPending: Promise<BatchPipelineResultWithContext<TOutput, COutput, R> | null> | null = null

    constructor(private callbacks: InterleavingCallbacks<TInput, TOutput, CInput, COutput, R>) {}

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.callbacks.onFeed(elements)
        // Wake a next() parked on the subpipeline so it loops back and pulls the
        // freshly delivered upstream input.
        this.newInputSignal.resolve()
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput, R> | null> {
        while (true) {
            // Arm a fresh wake-up before pulling. A feed landing during the pull
            // is still seen by the race below (not lost), while a stale signal
            // from an already-consumed feed does NOT over-eagerly pull the next
            // batch into an in-flight subpipeline (which would coalesce batches
            // that downstream stages like gather() expect to stay separate).
            this.newInputSignal.reset()

            const pulled = await this.callbacks.onSourcePull()
            if (pulled.kind === 'emit') {
                return pulled.batch
            }

            // Drain the subpipeline, racing against a concurrent feed: if the sub
            // is parked on slow in-flight work, a feed() landing now wakes us to
            // loop back and route the freshly delivered upstream input into it.
            if (!this.subPending) {
                this.subPending = this.callbacks.onProcessPull()
            }
            // Tag a rejection as a value so (a) when the signal wins instead the
            // sub branch is not an unhandled rejection, and (b) on a rejection we
            // clear subPending and the next call re-issues a fresh next() — a
            // poisoned subpipeline may still hand out other completed batches
            // before it re-rejects.
            const winner = await Promise.race([
                this.subPending.then(
                    (result) => ({ source: 'sub' as const, result }),
                    (error: unknown) => ({ source: 'sub-error' as const, error })
                ),
                this.newInputSignal.promise.then(() => ({ source: 'signal' as const })),
            ])

            if (winner.source === 'signal') {
                continue
            }

            this.subPending = null
            if (winner.source === 'sub-error') {
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
}
