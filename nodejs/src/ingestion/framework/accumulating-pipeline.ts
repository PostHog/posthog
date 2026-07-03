import pLimit from 'p-limit'

import { BatchPipeline, BatchPipelineResultWithContext, OkResultWithContext } from './batch-pipeline.interface'
import { createOkContext } from './helpers'
import { Pipeline } from './pipeline.interface'
import { ResettableSignal } from './resettable-signal'
import { isOkResult } from './results'

/** Context carried by every accumulation cycle's batch context. */
export interface AccumulationContext {
    batchId: number
}

/** Input to the beforeBatch hook — mirrors BatchingPipeline's beforeBatch. */
export interface BeforeAccumulationInput {
    batchId: number
}

/** What the beforeBatch hook produces: the fresh accumulator/manager handle for the next cycle. */
export interface BeforeAccumulationOutput<CBatch> {
    batchContext: CBatch & AccumulationContext
}

/**
 * Discriminated result of next(). The consumer reads `flushed` to decide what to do
 * with offsets: a `flushed: false` turn carries record-phase results (track offsets),
 * a `flushed: true` turn carries flush results (commit offsets).
 */
export type AccumulatingResult<TRecordOut, CRecordOut, TFlushOut, CFlushOut, R extends string = never> =
    | { flushed: false; elements: BatchPipelineResultWithContext<TRecordOut, CRecordOut, R> }
    | { flushed: true; elements: BatchPipelineResultWithContext<TFlushOut, CFlushOut, R> }

/**
 * Constructor config, ordered by when each part runs in a cycle: beforeBatch mints the accumulator,
 * pipeline folds events, shouldFlush/maxBatchAgeMs decide when to flush, then flushPipeline persists
 * the batch context.
 */
export interface AccumulatingPipelineConfig<
    TRecordIn extends object,
    TRecordOut,
    CRecordIn,
    CRecordOut,
    CBatch,
    TFlushOut,
    CFlushOut,
    R extends string = never,
> {
    /** Mints a fresh accumulator for each cycle — runs before the first feed and after every flush. */
    beforeBatch: Pipeline<BeforeAccumulationInput, BeforeAccumulationOutput<CBatch>, Record<string, never>>
    /** Per-message pipeline that folds records into the current cycle's accumulator. */
    pipeline: BatchPipeline<TRecordIn & CBatch & AccumulationContext, TRecordOut, CRecordIn, CRecordOut, R>
    /** Size trigger: flush when this returns true for the current accumulator. */
    shouldFlush: (batchContext: CBatch & AccumulationContext) => boolean
    /** Age trigger interval. The timer only marks a flush due; the flush executes inside next(). */
    maxBatchAgeMs: number
    /**
     * Flush pipeline that persists the batch context on a flush. It receives the whole batch context
     * as a single element and fans out over sub-units (e.g. per session) internally if it needs to.
     */
    flushPipeline: BatchPipeline<CBatch & AccumulationContext, TFlushOut, Record<string, never>, CFlushOut, R>
}

/**
 * Wraps a per-message `pipeline` that folds events into an external accumulator, and flushes that
 * accumulator through a separate `flushPipeline` of steps on a size or age trigger.
 *
 * Unlike BatchingPipeline — where each feed() is one batch — the accumulation boundary spans
 * many feed() calls and is decided by `shouldFlush` (size) plus an age timer. `beforeBatch`
 * mints a fresh accumulator after every flush (and before the first feed). Offsets live entirely
 * outside: feed/next emit results and the consumer owns all offset tracking and committing.
 *
 * LIVENESS INVARIANT — age-based flush requires next() to be called while idle.
 *
 * The age timer only sets flushDue; the flush executes inside next(). Something must therefore
 * keep calling next() even when the topic produces no messages. Today that is the Kafka
 * consumer's `callEachBatchWhenEmpty: true`: consume() returns [] every batchTimeoutMs (~500ms),
 * the empty batch still reaches handleEachBatch([]), and the resulting next() call observes
 * flushDue and flushes.
 *
 * If `callEachBatchWhenEmpty` is ever turned off, age-based flush MUST instead be driven by the
 * timer's signal.resolve() waking a blocking drain loop that runs next() to completion (see
 * waitForActivity()). Otherwise an idle accumulator with a buffered batch and no next() caller
 * would stall forever.
 */
export class AccumulatingPipeline<
    TRecordIn extends object,
    TRecordOut,
    CRecordIn,
    CRecordOut,
    CBatch,
    TFlushOut,
    CFlushOut,
    R extends string = never,
> {
    private currentBatchContext: (CBatch & AccumulationContext) | null = null
    private nextBatchId = 0
    private flushDue = false
    private timer?: ReturnType<typeof setInterval>

    // Serializes ALL accumulator access — feed (context mint + tag + record buffer push), the
    // next()/flush() drain, the size flush, and the timer-driven flush. This is what stops feed()
    // from tagging elements against a batch context that a concurrent flush is re-minting (which
    // would fold them into an already-flushed recorder and lose them), and keeps the external
    // accumulator single-threaded so the caller's record/flush steps carry no locking burden.
    // Mirrors BatchingPipeline's pump mutex.
    private pumpLimit = pLimit(1)

    // Wakes a consumer that PARKS on next() instead of polling (see LIVENESS INVARIANT above).
    // With callEachBatchWhenEmpty the consumer never parks, so this is currently only consumed
    // via waitForActivity(); it is the liveness mechanism for a future wake-driven drain loop.
    private signal = new ResettableSignal()

    private readonly beforePipeline: Pipeline<
        BeforeAccumulationInput,
        BeforeAccumulationOutput<CBatch>,
        Record<string, never>
    >
    private readonly pipeline: BatchPipeline<
        TRecordIn & CBatch & AccumulationContext,
        TRecordOut,
        CRecordIn,
        CRecordOut,
        R
    >
    private readonly flushPipeline: BatchPipeline<
        CBatch & AccumulationContext,
        TFlushOut,
        Record<string, never>,
        CFlushOut,
        R
    >
    private readonly shouldFlush: (batchContext: CBatch & AccumulationContext) => boolean
    private readonly maxBatchAgeMs: number

    constructor(
        config: AccumulatingPipelineConfig<
            TRecordIn,
            TRecordOut,
            CRecordIn,
            CRecordOut,
            CBatch,
            TFlushOut,
            CFlushOut,
            R
        >
    ) {
        this.beforePipeline = config.beforeBatch
        this.pipeline = config.pipeline
        this.flushPipeline = config.flushPipeline
        this.shouldFlush = config.shouldFlush
        this.maxBatchAgeMs = config.maxBatchAgeMs
    }

    /** Arms the age timer. Idempotent-ish: call once after construction. */
    public start(): void {
        this.armTimer()
    }

    /**
     * Clears the age timer and performs a final flush of whatever is accumulated, so the last
     * partial batch is not lost on shutdown. Callers must drain next() to null first so the
     * record buffer is empty and folded into the accumulator.
     */
    public stop(): Promise<AccumulatingResult<TRecordOut, CRecordOut, TFlushOut, CFlushOut, R> | null> {
        if (this.timer) {
            clearInterval(this.timer)
            this.timer = undefined
        }
        return this.pumpLimit(() => this.drainAndFlush())
    }

    private async drainAndFlush(): Promise<AccumulatingResult<TRecordOut, CRecordOut, TFlushOut, CFlushOut, R> | null> {
        await this.drain(this.pipeline)
        return this.flushNow()
    }

    public feed(elements: OkResultWithContext<TRecordIn, CRecordIn>[]): Promise<void> {
        // Under the pump mutex so the context read + tagging + buffer push is atomic w.r.t. a
        // concurrent flush re-minting the batch context (e.g. revoke-triggered flush).
        return this.pumpLimit(async () => {
            const batchContext = await this.ensureBatchContext()
            const tagged = elements.map((element) => ({
                result: { ...element.result, value: { ...element.result.value, ...batchContext } },
                context: element.context,
            }))
            this.pipeline.feed(tagged)
        })
    }

    public next(): Promise<AccumulatingResult<TRecordOut, CRecordOut, TFlushOut, CFlushOut, R> | null> {
        return this.pumpLimit(() => this.pump())
    }

    /**
     * Forces an immediate flush: drains any buffered record work into the accumulator, then flushes.
     * The age timer keeps running. Used on Kafka partition revocation — rather than reaching into the
     * live batch to discard the revoked partition, we process what we have and flush it.
     */
    public flush(): Promise<AccumulatingResult<TRecordOut, CRecordOut, TFlushOut, CFlushOut, R> | null> {
        return this.pumpLimit(() => this.drainAndFlush())
    }

    /**
     * Resolves when there may be new work (the age timer fired). A wake-driven drain loop awaits
     * this between null results instead of polling. See LIVENESS INVARIANT above.
     */
    public async waitForActivity(): Promise<void> {
        await this.signal.wait()
        this.signal.reset()
    }

    private async pump(): Promise<AccumulatingResult<TRecordOut, CRecordOut, TFlushOut, CFlushOut, R> | null> {
        // Drain the record (main) pipeline first; yield its results so the consumer can track offsets.
        const recorded = await this.drain(this.pipeline)
        if (recorded.length > 0) {
            return { flushed: false, elements: recorded }
        }

        // Main pipeline empty → flush on size or age.
        const sizeDue = this.currentBatchContext !== null && this.shouldFlush(this.currentBatchContext)
        if (this.flushDue || sizeDue) {
            return await this.flushNow()
        }

        return null
    }

    private async flushNow(): Promise<AccumulatingResult<TRecordOut, CRecordOut, TFlushOut, CFlushOut, R> | null> {
        this.flushDue = false
        this.rearmTimer()

        if (this.currentBatchContext === null) {
            return null
        }

        // Hand the whole batch context to the flush pipeline as a single element; the flush pipeline
        // fans out over sub-units (e.g. per session) internally if it needs per-unit steps.
        this.flushPipeline.feed([createOkContext(this.currentBatchContext, {})])
        const elements = await this.drain(this.flushPipeline)
        this.currentBatchContext = await this.runBeforeBatch()
        return { flushed: true, elements }
    }

    private async ensureBatchContext(): Promise<CBatch & AccumulationContext> {
        if (this.currentBatchContext === null) {
            this.currentBatchContext = await this.runBeforeBatch()
        }
        return this.currentBatchContext
    }

    private async runBeforeBatch(): Promise<CBatch & AccumulationContext> {
        const batchId = this.nextBatchId++
        const result = await this.beforePipeline.process(createOkContext({ batchId }, {}))
        if (!isOkResult(result.result)) {
            throw new Error(`accumulating_pipeline beforeBatch returned non-ok result for batch ${batchId}`)
        }
        // Force batchId regardless of what the hook returned, mirroring BatchingPipeline.
        return { ...result.result.value.batchContext, batchId }
    }

    private async drain<T, C>(
        pipeline: BatchPipeline<any, T, any, C, R>
    ): Promise<BatchPipelineResultWithContext<T, C, R>> {
        const all: BatchPipelineResultWithContext<T, C, R> = []
        let result = await pipeline.next()
        while (result !== null) {
            all.push(...result)
            result = await pipeline.next()
        }
        return all
    }

    private armTimer(): void {
        this.timer = setInterval(() => {
            this.flushDue = true
            this.signal.resolve()
        }, this.maxBatchAgeMs)
    }

    // Re-arm so the age boundary is measured from this flush, not from the last timer tick —
    // matching today's lastFlushTime reset. No-op once the timer has been cleared by stop().
    private rearmTimer(): void {
        if (this.timer) {
            clearInterval(this.timer)
            this.armTimer()
        }
    }
}
