import pLimit from 'p-limit'

import { BatchPipeline, BatchPipelineResultWithContext, OkResultWithContext } from './batch-pipeline.interface'
import { BatchResult, FeedResult } from './batching-pipeline'
import { createOkContext } from './helpers'
import { Pipeline } from './pipeline.interface'
import { ResettableSignal } from './resettable-signal'
import { isOkResult } from './results'

/** Context carried by every accumulation cycle's batch context. */
export interface AccumulationContext {
    batchId: number
}

/**
 * The record pipeline the accumulating pipeline drives. Narrower than a full {@link BatchPipeline}:
 * `next()` returns a {@link BatchResult} (elements plus batch-level side effects), which is what a
 * {@link BatchingPipeline} produces — its afterBatch trims each result and surfaces its produces. A
 * `BatchingPipeline` is structurally assignable to this.
 */
export interface RecordPipeline<TInput, CInput, TOutput, COutput, R extends string = never> {
    feed(elements: OkResultWithContext<TInput, CInput>[]): Promise<FeedResult>
    next(): Promise<BatchResult<BatchPipelineResultWithContext<TOutput, COutput, R>> | null>
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
 * Discriminated result of next(). The consumer reads `flushed` to decide what to do: a
 * `flushed: false` turn carries the record pipeline's trimmed results, a `flushed: true` turn
 * carries the flush results (whose steps commit the offsets the batch covers). Both variants carry
 * the side effects surfaced this turn (the record pipeline's DLQ/overflow produces on record turns,
 * plus the record-phase produces on a drain-and-flush) so the caller can make them durable before a
 * later flush commits offsets. Offsets themselves are tracked inside the record pipeline's afterBatch.
 */
export type AccumulatingResult<TRecordOut, CRecordOut, TFlushOut, CFlushOut, R extends string = never> =
    | {
          flushed: false
          elements: BatchPipelineResultWithContext<TRecordOut, CRecordOut, R>
          sideEffects: Promise<unknown>[]
      }
    | {
          flushed: true
          elements: BatchPipelineResultWithContext<TFlushOut, CFlushOut, R>
          sideEffects: Promise<unknown>[]
      }

/**
 * The single element handed to the flush pipeline on a flush: the batch context (the accumulator)
 * plus every record result accumulated since the last flush, in feed order. Mirrors
 * BatchingPipeline's {@link AfterBatchInput} so flush steps can both drain the accumulator (via
 * `batchContext`) and read per-record data (via `elements`, e.g. to compute per-message latency).
 */
export interface AccumulatedFlushInput<TRecordOut, CRecordOut, CBatch, R extends string = never> {
    elements: BatchPipelineResultWithContext<TRecordOut, CRecordOut, R>
    batchContext: CBatch & AccumulationContext
}

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
    pipeline: RecordPipeline<TRecordIn & CBatch & AccumulationContext, CRecordIn, TRecordOut, CRecordOut, R>
    /** Size trigger: flush when this returns true for the current accumulator. */
    shouldFlush: (batchContext: CBatch & AccumulationContext) => boolean
    /** Age trigger interval. The timer only marks a flush due; the flush executes inside next(). */
    maxBatchAgeMs: number
    /**
     * Flush pipeline that persists the batch on a flush. It receives a single
     * {@link AccumulatedFlushInput} — the batch context plus every accumulated record result in feed
     * order — and fans out over sub-units (e.g. per session) internally if it needs to.
     */
    flushPipeline: BatchPipeline<
        AccumulatedFlushInput<TRecordOut, CRecordOut, CBatch, R>,
        TFlushOut,
        Record<string, never>,
        CFlushOut,
        R
    >
}

/**
 * Wraps a per-message `pipeline` that folds events into an external accumulator, and flushes that
 * accumulator through a separate `flushPipeline` of steps on a size or age trigger.
 *
 * Unlike BatchingPipeline — where each feed() is one batch — the accumulation boundary spans
 * many feed() calls and is decided by `shouldFlush` (size) plus an age timer. `beforeBatch`
 * mints a fresh accumulator after every flush (and before the first feed). The record pipeline's
 * output (typically a BatchingPipeline whose afterBatch trims each result and records its offset)
 * accumulates in feed order and is handed to the flush pipeline as {@link AccumulatedFlushInput};
 * the flush pipeline both persists the accumulator and commits the offsets its records covered.
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
    private readonly pipeline: RecordPipeline<
        TRecordIn & CBatch & AccumulationContext,
        CRecordIn,
        TRecordOut,
        CRecordOut,
        R
    >
    private readonly flushPipeline: BatchPipeline<
        AccumulatedFlushInput<TRecordOut, CRecordOut, CBatch, R>,
        TFlushOut,
        Record<string, never>,
        CFlushOut,
        R
    >
    private readonly shouldFlush: (batchContext: CBatch & AccumulationContext) => boolean
    private readonly maxBatchAgeMs: number

    // Record results accumulated (in feed order) since the last flush, handed to the flush pipeline
    // as AccumulatedFlushInput.elements. The record pipeline's afterBatch has already trimmed these
    // to whatever the flush needs, so this holds lightweight rows, not the full fed payloads.
    private flushBuffer: BatchPipelineResultWithContext<TRecordOut, CRecordOut, R> = []

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
        // Drain any buffered record work into the accumulator FIRST so a revoke/stop flush also runs
        // the record pipeline's afterBatch on it (offsets tracked, elements trimmed) before flushing.
        const { elements: recorded, sideEffects } = await this.drainRecord()
        this.flushBuffer.push(...recorded)
        const flushed = await this.flushNow()
        if (flushed === null) {
            return null
        }
        // Surface the record-phase side effects (DLQ/overflow produces) alongside the flush's, so the
        // caller can make them durable before committing the offsets this flush covers.
        return { ...flushed, sideEffects: [...sideEffects, ...flushed.sideEffects] }
    }

    public feed(elements: OkResultWithContext<TRecordIn, CRecordIn>[]): Promise<void> {
        // An empty feed carries no records — skip it rather than push an empty batch into the record
        // pipeline. A BatchingPipeline registers an empty feed as a batch with no messages, which never
        // completes (its afterBatch fires only when the last message exits), so its next() would then
        // fault. The idle Kafka tick (callEachBatchWhenEmpty) feeds [] regularly, so this is hot.
        if (elements.length === 0) {
            return Promise.resolve()
        }
        // Under the pump mutex so the context read + tagging + buffer push is atomic w.r.t. a
        // concurrent flush re-minting the batch context (e.g. revoke-triggered flush).
        return this.pumpLimit(async () => {
            const batchContext = await this.ensureBatchContext()
            const tagged = elements.map((element) => ({
                result: { ...element.result, value: { ...element.result.value, ...batchContext } },
                context: element.context,
            }))
            await this.pipeline.feed(tagged)
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
        // Drain the record (main) pipeline first and accumulate its afterBatch output — already
        // trimmed and in feed order — into the flush buffer, keeping its surfaced side effects.
        const { elements: recorded, sideEffects } = await this.drainRecord()
        this.flushBuffer.push(...recorded)
        if (recorded.length > 0 || sideEffects.length > 0) {
            return { flushed: false, elements: recorded, sideEffects }
        }

        // Main pipeline empty → flush on size or age.
        const sizeDue = this.currentBatchContext !== null && this.shouldFlush(this.currentBatchContext)
        if (this.flushDue || sizeDue) {
            return await this.flushNow()
        }

        return null
    }

    /**
     * Drains the record pipeline to null, flattening its BatchResults into one feed-ordered element
     * list and concatenating the batch-level side effects (the produces its afterBatch surfaced).
     */
    private async drainRecord(): Promise<{
        elements: BatchPipelineResultWithContext<TRecordOut, CRecordOut, R>
        sideEffects: Promise<unknown>[]
    }> {
        const elements: BatchPipelineResultWithContext<TRecordOut, CRecordOut, R> = []
        const sideEffects: Promise<unknown>[] = []
        let result = await this.pipeline.next()
        while (result !== null) {
            elements.push(...result.elements)
            sideEffects.push(...(result.sideEffects ?? []))
            result = await this.pipeline.next()
        }
        return { elements, sideEffects }
    }

    private async flushNow(): Promise<AccumulatingResult<TRecordOut, CRecordOut, TFlushOut, CFlushOut, R> | null> {
        this.flushDue = false
        this.rearmTimer()

        if (this.currentBatchContext === null) {
            return null
        }

        // Hand the flush pipeline one element: the batch context plus the accumulated record results
        // in feed order. Reset the buffer and re-mint the batch context for the next cycle.
        const flushInput: AccumulatedFlushInput<TRecordOut, CRecordOut, CBatch, R> = {
            elements: this.flushBuffer,
            batchContext: this.currentBatchContext,
        }
        this.flushPipeline.feed([createOkContext(flushInput, {})])
        const elements = await this.drain(this.flushPipeline)
        // Aggregate any side effects the flush steps left on their results (typically none, but keep
        // it correct so a flush-step produce is made durable before the caller commits offsets).
        const sideEffects = elements.flatMap((element) => element.context.sideEffects)
        this.flushBuffer = []
        this.currentBatchContext = await this.runBeforeBatch()
        return { flushed: true, elements, sideEffects }
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
