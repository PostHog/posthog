import pLimit from 'p-limit'

import { ChunkPipeline, ChunkPipelineResultWithContext, OkResultWithContext } from './chunk-pipeline.interface'
import { createOkContext } from './helpers'
import { Pipeline } from './pipeline.interface'
import { ResettableSignal } from './resettable-signal'
import { PipelineResult, isOkResult } from './results'

/** Context carried by every accumulation cycle's cycle context. */
export interface CycleContext {
    cycleId: number
}

/** Input to the beforeCycle hook. */
export interface BeforeCycleInput {
    cycleId: number
}

/** What the beforeCycle hook produces: the fresh accumulator/manager handle for the next cycle. */
export interface BeforeCycleOutput<CCycle> {
    cycleContext: CCycle & CycleContext
}

/**
 * Discriminated result of next(). The consumer reads `flushed` to decide what to do: a
 * `flushed: false` turn carries the record results, a `flushed: true` turn carries the flush
 * results. Both variants carry the side effects surfaced this turn so the caller can make them
 * durable.
 */
export type AccumulatingResult<TRecordOut, TFlushOut, CFlushOut, R extends string = never> =
    | {
          flushed: false
          elements: PipelineResult<TRecordOut, R>[]
          sideEffects: Promise<unknown>[]
      }
    | {
          flushed: true
          elements: ChunkPipelineResultWithContext<TFlushOut, CFlushOut, R>
          sideEffects: Promise<unknown>[]
      }

/**
 * The single element handed to the flush pipeline on a flush: the cycle context (the accumulator)
 * plus every record result accumulated since the last flush, in drain order. Flush steps can both
 * drain the accumulator (via `cycleContext`) and read per-record data (via `elements` — e.g. to
 * commit the Kafka offsets the cycle covers). The elements are bare results — contexts were
 * dropped at drain time — and the record pipeline's tail shapes their values, so the buffer holds
 * lightweight rows instead of pinning raw payloads.
 */
export interface CycleFlushInput<TRecordOut, CCycle, R extends string = never> {
    elements: PipelineResult<TRecordOut, R>[]
    cycleContext: CCycle & CycleContext
}

/**
 * Constructor config, ordered by when each part runs in a cycle: beforeCycle mints the accumulator,
 * pipeline folds events (and trims what accumulates), shouldFlush/maxCycleAgeMs decide when to
 * flush, then flushPipeline persists the cycle.
 */
export interface AccumulatingPipelineConfig<
    TRecordIn extends object,
    TRecordOut,
    CRecordIn,
    CRecordOut,
    CCycle,
    TFlushOut,
    CFlushOut,
    R extends string = never,
> {
    /** Mints a fresh accumulator for each cycle — runs before the first feed and after every flush. */
    beforeCycle: Pipeline<BeforeCycleInput, BeforeCycleOutput<CCycle>, Record<string, never>>
    /**
     * Per-message pipeline that folds records into the current cycle's accumulator — a plain chunk
     * pipeline of steps. The cycle boundary lives entirely in this class; the pipeline knows
     * nothing about cycles or flushes. Every drained result accumulates for the flush as a bare
     * result (contexts are dropped at drain time), so the pipeline's tail should mapElements each
     * result — OK and non-OK alike — to the lightweight row the flush reads.
     */
    pipeline: ChunkPipeline<TRecordIn & CCycle & CycleContext, TRecordOut, CRecordIn, CRecordOut, R>
    /** Size trigger: flush when this returns true for the current accumulator. */
    shouldFlush: (cycleContext: CCycle & CycleContext) => boolean
    /** Age trigger interval. The timer only marks a flush due; the flush executes inside next(). */
    maxCycleAgeMs: number
    /**
     * Flush pipeline that persists the cycle on a flush. It receives a single
     * {@link CycleFlushInput} — the cycle context plus every accumulated record result — and fans
     * out over sub-units (e.g. per session) internally if it needs to.
     */
    flushPipeline: ChunkPipeline<CycleFlushInput<TRecordOut, CCycle, R>, TFlushOut, Record<string, never>, CFlushOut, R>
}

/**
 * Wraps a per-message `pipeline` that folds events into an external accumulator, and flushes that
 * accumulator through a separate `flushPipeline` of steps on a size or age trigger.
 *
 * Unlike BatchingPipeline — where each feed() is one batch — the accumulation cycle spans many
 * feed() calls and is closed by `shouldFlush` (size) plus an age timer. `beforeCycle` mints a
 * fresh accumulator after every flush (and before the first feed). The record pipeline is a plain
 * chunk pipeline; as its results drain, this class surfaces any side effects still on the element
 * contexts (so they surface exactly once, on the turn that produced them) and accumulates every
 * result for the flush. The pipeline itself never commits offsets and never schedules side
 * effects — flush steps and the caller own both.
 *
 * A sibling of BatchingPipeline, deliberately not a reuse of BufferingChunkPipeline (that one is a
 * passthrough re-emit buffer used by filterMap); the defining difference from both is the cycle
 * boundary spanning many feed() calls.
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
 * waitForActivity()). Otherwise an idle accumulator with a buffered cycle and no next() caller
 * would stall forever.
 */
export class AccumulatingPipeline<
    TRecordIn extends object,
    TRecordOut,
    CRecordIn,
    CRecordOut,
    CCycle,
    TFlushOut,
    CFlushOut,
    R extends string = never,
> {
    private currentCycleContext: (CCycle & CycleContext) | null = null
    private nextCycleId = 0
    private flushDue = false
    private timer?: ReturnType<typeof setInterval>

    // Serializes ALL accumulator access — feed (context mint + tag + record buffer push), the
    // next()/flush() drain, the size flush, and the timer-driven flush. This is what stops feed()
    // from tagging elements against a cycle context that a concurrent flush is re-minting (which
    // would fold them into an already-flushed recorder and lose them), and keeps the external
    // accumulator single-threaded so the caller's record/flush steps carry no locking burden.
    // Mirrors BatchingPipeline's pump mutex.
    private pumpLimit = pLimit(1)

    // Wakes a consumer that PARKS on next() instead of polling (see LIVENESS INVARIANT above).
    // With callEachBatchWhenEmpty the consumer never parks, so this is currently only consumed
    // via waitForActivity(); it is the liveness mechanism for a future wake-driven drain loop.
    private signal = new ResettableSignal()

    private readonly beforePipeline: Pipeline<BeforeCycleInput, BeforeCycleOutput<CCycle>, Record<string, never>>
    private readonly pipeline: ChunkPipeline<TRecordIn & CCycle & CycleContext, TRecordOut, CRecordIn, CRecordOut, R>
    private readonly flushPipeline: ChunkPipeline<
        CycleFlushInput<TRecordOut, CCycle, R>,
        TFlushOut,
        Record<string, never>,
        CFlushOut,
        R
    >
    private readonly shouldFlush: (cycleContext: CCycle & CycleContext) => boolean
    private readonly maxCycleAgeMs: number

    // Record results accumulated (in drain order) since the last flush, handed to the flush
    // pipeline as CycleFlushInput.elements. The record pipeline's tail has already trimmed these
    // to whatever the flush needs, so this holds lightweight rows, not the full fed payloads.
    private flushBuffer: PipelineResult<TRecordOut, R>[] = []

    constructor(
        config: AccumulatingPipelineConfig<
            TRecordIn,
            TRecordOut,
            CRecordIn,
            CRecordOut,
            CCycle,
            TFlushOut,
            CFlushOut,
            R
        >
    ) {
        this.beforePipeline = config.beforeCycle
        this.pipeline = config.pipeline
        this.flushPipeline = config.flushPipeline
        this.shouldFlush = config.shouldFlush
        this.maxCycleAgeMs = config.maxCycleAgeMs
    }

    /** Arms the age timer. Idempotent-ish: call once after construction. */
    public start(): void {
        this.armTimer()
    }

    /**
     * Clears the age timer and performs a final flush of whatever is accumulated, so the last
     * partial cycle is not lost on shutdown. Callers must drain next() to null first so the
     * record buffer is empty and folded into the accumulator.
     */
    public stop(): Promise<AccumulatingResult<TRecordOut, TFlushOut, CFlushOut, R> | null> {
        if (this.timer) {
            clearInterval(this.timer)
            this.timer = undefined
        }
        return this.pumpLimit(() => this.drainAndFlush())
    }

    private async drainAndFlush(): Promise<AccumulatingResult<TRecordOut, TFlushOut, CFlushOut, R> | null> {
        // Drain any buffered record work into the accumulator FIRST so a revoke/stop flush covers
        // it too — the flush then persists and commits everything drained so far.
        const { elements: recorded, sideEffects } = await this.drainRecord()
        this.flushBuffer.push(...recorded)
        const flushed = await this.flushNow()
        if (flushed === null) {
            return null
        }
        // Surface the record-phase side effects alongside the flush's, so the caller can make them
        // durable.
        return { ...flushed, sideEffects: [...sideEffects, ...flushed.sideEffects] }
    }

    public feed(elements: OkResultWithContext<TRecordIn, CRecordIn>[]): Promise<void> {
        // An empty feed carries no records — skip it rather than take the mutex and mint a cycle
        // context for nothing. The idle Kafka tick (callEachBatchWhenEmpty) feeds [] regularly, so
        // this is hot.
        if (elements.length === 0) {
            return Promise.resolve()
        }
        // Under the pump mutex so the context read + tagging + buffer push is atomic w.r.t. a
        // concurrent flush re-minting the cycle context (e.g. revoke-triggered flush).
        return this.pumpLimit(async () => {
            const cycleContext = await this.ensureCycleContext()
            const tagged = elements.map((element) => ({
                result: { ...element.result, value: { ...element.result.value, ...cycleContext } },
                context: element.context,
            }))
            this.pipeline.feed(tagged)
        })
    }

    public next(): Promise<AccumulatingResult<TRecordOut, TFlushOut, CFlushOut, R> | null> {
        return this.pumpLimit(() => this.pump())
    }

    /**
     * Forces an immediate flush: drains any buffered record work into the accumulator, then flushes.
     * The age timer keeps running. Used on Kafka partition revocation — rather than reaching into the
     * live cycle to discard the revoked partition, we process what we have and flush it.
     */
    public flush(): Promise<AccumulatingResult<TRecordOut, TFlushOut, CFlushOut, R> | null> {
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

    private async pump(): Promise<AccumulatingResult<TRecordOut, TFlushOut, CFlushOut, R> | null> {
        // Drain the record (main) pipeline first and accumulate its results — already trimmed and
        // in drain order — into the flush buffer, keeping the surfaced side effects.
        const { elements: recorded, sideEffects } = await this.drainRecord()
        this.flushBuffer.push(...recorded)
        if (recorded.length > 0 || sideEffects.length > 0) {
            return { flushed: false, elements: recorded, sideEffects }
        }

        // Main pipeline empty → flush on size or age.
        const sizeDue = this.currentCycleContext !== null && this.shouldFlush(this.currentCycleContext)
        if (this.flushDue || sizeDue) {
            return await this.flushNow()
        }

        return null
    }

    /**
     * Drains the record pipeline to null. Any side effects still on an element's context are
     * lifted into the turn's side-effect list and cleared from the element — they surface exactly
     * once, on the turn that produced them, and never again at flush time.
     */
    private async drainRecord(): Promise<{
        elements: PipelineResult<TRecordOut, R>[]
        sideEffects: Promise<unknown>[]
    }> {
        const drained: ChunkPipelineResultWithContext<TRecordOut, CRecordOut, R> = []
        let result = await this.pipeline.next()
        while (result !== null) {
            drained.push(...result)
            result = await this.pipeline.next()
        }
        if (drained.length === 0) {
            return { elements: [], sideEffects: [] }
        }

        const sideEffects = drained.flatMap((element) => element.context.sideEffects)
        return { elements: drained.map((element) => element.result), sideEffects }
    }

    private async flushNow(): Promise<AccumulatingResult<TRecordOut, TFlushOut, CFlushOut, R> | null> {
        this.flushDue = false
        this.rearmTimer()

        if (this.currentCycleContext === null) {
            return null
        }

        // Hand the flush pipeline one element: the cycle context plus the accumulated record results
        // in drain order. Reset the buffer and re-mint the cycle context for the next cycle.
        const flushInput: CycleFlushInput<TRecordOut, CCycle, R> = {
            elements: this.flushBuffer,
            cycleContext: this.currentCycleContext,
        }
        this.flushPipeline.feed([createOkContext(flushInput, {})])
        const elements = await this.drain(this.flushPipeline)
        // Aggregate any side effects the flush steps left on their results, so the caller can make
        // a flush-step produce durable.
        const sideEffects = elements.flatMap((element) => element.context.sideEffects)
        this.flushBuffer = []
        this.currentCycleContext = await this.runBeforeCycle()
        return { flushed: true, elements, sideEffects }
    }

    private async ensureCycleContext(): Promise<CCycle & CycleContext> {
        if (this.currentCycleContext === null) {
            this.currentCycleContext = await this.runBeforeCycle()
        }
        return this.currentCycleContext
    }

    private async runBeforeCycle(): Promise<CCycle & CycleContext> {
        const cycleId = this.nextCycleId++
        const result = await this.beforePipeline.process(createOkContext({ cycleId }, {}))
        if (!isOkResult(result.result)) {
            throw new Error(`accumulating_pipeline beforeCycle returned non-ok result for cycle ${cycleId}`)
        }
        // Force cycleId regardless of what the hook returned, mirroring BatchingPipeline's batchId.
        return { ...result.result.value.cycleContext, cycleId }
    }

    private async drain<T, C>(
        pipeline: ChunkPipeline<any, T, any, C, R>
    ): Promise<ChunkPipelineResultWithContext<T, C, R>> {
        const all: ChunkPipelineResultWithContext<T, C, R> = []
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
        }, this.maxCycleAgeMs)
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
