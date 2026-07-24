import { ChunkPipeline, ChunkPipelineResultWithContext, OkResultWithContext } from './chunk-pipeline.interface'

/**
 * Omitted (plain `gather()`): a barrier — drain the sub-pipeline until it
 * reports empty, then emit everything as one chunk. Callers rely on this when
 * a downstream chunk step must see every in-flight result at once (e.g. the
 * session replay mark-seen step requires all session keys resolved first).
 *
 * Provided: a bounded coalescer with `fetch.min.bytes` / `fetch.max.wait`
 * semantics. Results accumulate across pulls and the chunk is emitted as soon
 * as any of these holds:
 * - `minItems` results have accumulated (enough that waiting longer isn't
 *   worth it),
 * - the upstream reports empty (`null`) — nothing is in flight, so waiting
 *   would only speculate on future feeds,
 * - a pull is still in flight but `maxWaitMs` has elapsed since the chunk's
 *   first result — the in-flight pull carries over to the next call, unawaited
 *   and unlost.
 *
 * Use the bounded mode where chunk steps batch for efficiency only, so results
 * that already completed are never held back behind slow in-flight work
 * (concurrentBatches > 1 on the ingestion API).
 */
export interface GatherOptions {
    /**
     * Upper bound (ms) on how long a chunk may keep accumulating while
     * upstream work is in flight, measured from the chunk's first result.
     */
    maxWaitMs: number
    /** Emit as soon as this many results have accumulated. Default: unbounded. */
    minItems?: number
}

/**
 * Collects upstream chunks into larger ones. See {@link GatherOptions} for the
 * two emission policies (barrier vs bounded).
 *
 * Bounded-mode failure handling: results accumulated before an upstream
 * failure are emitted first; the rejected pull is retained so every subsequent
 * `next()` rejects with that error permanently — the drain-then-reject
 * convention of the other stages.
 */
export class GatheringChunkPipeline<TInput, TOutput, CInput, COutput = CInput, R extends string = never>
    implements ChunkPipeline<TInput, TOutput, CInput, COutput, R>
{
    // Bounded mode only: a pull that outlived its chunk (deadline or minItems
    // emission) carries over so the next call re-awaits it instead of issuing
    // a duplicate pull.
    private pendingPull: Promise<ChunkPipelineResultWithContext<TOutput, COutput, R> | null> | null = null
    private accumulator: ChunkPipelineResultWithContext<TOutput, COutput, R> = []
    // Absolute emission deadline, armed when the accumulator gains its first result.
    private deadlineAt: number | null = null

    constructor(
        private subPipeline: ChunkPipeline<TInput, TOutput, CInput, COutput, R>,
        private options?: GatherOptions
    ) {}

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.subPipeline.feed(elements)
    }

    next(): Promise<ChunkPipelineResultWithContext<TOutput, COutput, R> | null> {
        return this.options ? this.nextBounded(this.options) : this.nextBarrier()
    }

    private async nextBarrier(): Promise<ChunkPipelineResultWithContext<TOutput, COutput, R> | null> {
        const allResults: ChunkPipelineResultWithContext<TOutput, COutput, R> = []

        let result = await this.subPipeline.next()
        while (result !== null) {
            result.forEach((resultWithContext) => {
                allResults.push(resultWithContext)
            })
            result = await this.subPipeline.next()
        }

        if (allResults.length === 0) {
            return null
        }

        return allResults
    }

    private async nextBounded(
        options: GatherOptions
    ): Promise<ChunkPipelineResultWithContext<TOutput, COutput, R> | null> {
        const minItems = options.minItems ?? Infinity

        while (true) {
            if (this.accumulator.length >= minItems) {
                return this.emit()
            }
            if (!this.pendingPull) {
                this.pendingPull = this.subPipeline.next()
            }

            if (this.accumulator.length === 0) {
                // Nothing to emit yet, so there is no deadline to honor — wait
                // for the pull outright. On rejection the pull stays retained,
                // so later calls rethrow permanently.
                const result = await this.pendingPull
                this.pendingPull = null
                if (result === null) {
                    return null
                }
                this.accumulator.push(...result)
                this.deadlineAt = Date.now() + options.maxWaitMs
                continue
            }

            const remainingMs = this.deadlineAt! - Date.now()
            if (remainingMs <= 0) {
                return this.emit()
            }

            let timer: NodeJS.Timeout | undefined
            let winner:
                | { timedOut: true }
                | { timedOut: false; result: ChunkPipelineResultWithContext<TOutput, COutput, R> | null }
            try {
                winner = await Promise.race([
                    this.pendingPull.then((result) => ({ timedOut: false as const, result })),
                    new Promise<{ timedOut: true }>((resolve) => {
                        timer = setTimeout(() => resolve({ timedOut: true }), remainingMs)
                    }),
                ])
            } catch {
                // Upstream failed: hand out what completed before it. The
                // retained rejected pull makes the next call rethrow.
                return this.emit()
            } finally {
                clearTimeout(timer)
            }

            if (winner.timedOut) {
                // The pull is still in flight past the deadline. Emit what
                // already completed; the next call re-awaits the carried pull.
                return this.emit()
            }

            this.pendingPull = null
            if (winner.result === null) {
                // Upstream is empty: nothing in flight, so emit rather than
                // linger speculating on future feeds.
                return this.emit()
            }
            this.accumulator.push(...winner.result)
        }
    }

    private emit(): ChunkPipelineResultWithContext<TOutput, COutput, R> {
        const results = this.accumulator
        this.accumulator = []
        this.deadlineAt = null
        return results
    }
}
