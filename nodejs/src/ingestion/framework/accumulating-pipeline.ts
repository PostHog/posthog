import pLimit from 'p-limit'

import { ChunkPipeline, ChunkPipelineResultWithContext, OkResultWithContext } from './chunk-pipeline.interface'
import { createOkContext } from './helpers'
import { PipelineResultWithContext } from './pipeline.interface'
import { ResettableSignal } from './resettable-signal'

/**
 * Folds one drained record result into the cycle state. Runs on every result the pipeline emits,
 * one element at a time — OK and non-OK alike, with the context still attached — exactly once, so
 * this is where per-message bookkeeping lives: session replay records OK results into the state's
 * batch recorder and folds every message's partition and offset into it (drops and DLQs too, so
 * the flush's commit advances past them). Extract what the flush needs into the state and let the
 * element go — nothing is retained after the reduce, so the cycle never pins per-message payloads.
 */
export type CycleReducer<TState, TRecordOut, CRecordOut, R extends string = never> = (
    state: TState,
    element: PipelineResultWithContext<TRecordOut, CRecordOut, R>
) => TState | Promise<TState>

/**
 * Discriminated result of next(). The consumer reads `flushed` to decide what to do: a
 * `flushed: false` turn means record work happened (its results were reduced into the cycle
 * state), a `flushed: true` turn carries the flush results. Both variants carry the side effects
 * surfaced this turn so the caller can make them durable.
 */
export type AccumulatingResult<TFlushOut, CFlushOut, R extends string = never> =
    | {
          flushed: false
          sideEffects: Promise<unknown>[]
      }
    | {
          flushed: true
          elements: ChunkPipelineResultWithContext<TFlushOut, CFlushOut, R>
          sideEffects: Promise<unknown>[]
      }

/**
 * Constructor config, ordered by when each part runs in a cycle: initialState mints the cycle's
 * accumulator, pipeline processes events, reduce folds every drained result into the state,
 * shouldFlush/maxCycleAgeMs decide when to flush, then flushPipeline persists the state.
 */
export interface AccumulatingPipelineConfig<
    TRecordIn,
    TRecordOut,
    CRecordIn,
    CRecordOut,
    TState,
    TFlushOut,
    CFlushOut,
    R extends string = never,
> {
    /**
     * Per-message pipeline — a plain chunk pipeline of steps. It knows nothing about cycles or
     * flushes: it takes messages in and emits the data the reducer folds into the state.
     */
    pipeline: ChunkPipeline<TRecordIn, TRecordOut, CRecordIn, CRecordOut, R>
    /**
     * Mints the cycle state — the one accumulator everything folds into (e.g. a fresh session
     * batch recorder plus the offsets to commit). Runs lazily: for the first drained result, and
     * again after every flush.
     */
    initialState: () => TState | Promise<TState>
    /** Folds every drained record result into the cycle state — see {@link CycleReducer}. */
    reduce: CycleReducer<TState, TRecordOut, CRecordOut, R>
    /** Size trigger: flush when this returns true for the current state. */
    shouldFlush: (state: TState) => boolean
    /** Age trigger interval. The timer only marks a flush due; the flush executes inside next(). */
    maxCycleAgeMs: number
    /**
     * Flush pipeline that persists the cycle on a flush. It receives a single element — the cycle
     * state — and fans out over sub-units (e.g. per session) internally if it needs to.
     */
    flushPipeline: ChunkPipeline<TState, TFlushOut, Record<string, never>, CFlushOut, R>
}

/**
 * Wraps a per-message `pipeline` and folds its results into an explicit cycle state, flushing that
 * state through a separate `flushPipeline` of steps on a size or age trigger.
 *
 * Unlike BatchingPipeline — where each feed() is one batch — the accumulation cycle spans many
 * feed() calls and is closed by `shouldFlush` (size) plus an age timer. `initialState` mints the
 * cycle's accumulator lazily and again after every flush. The record pipeline is a plain chunk
 * pipeline that never sees the cycle; as its results drain, this class surfaces any side effects
 * still on the element contexts (so they surface exactly once, on the turn that produced them) and
 * folds every result into the state via `reduce` — then lets the element go, so nothing
 * accumulates beyond the state. The pipeline itself never commits offsets and never schedules side
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
    TRecordIn,
    TRecordOut,
    CRecordIn,
    CRecordOut,
    TState,
    TFlushOut,
    CFlushOut,
    R extends string = never,
> {
    private currentState: TState | null = null
    private flushDue = false
    private timer?: ReturnType<typeof setInterval>

    // Serializes state access — the next()/flush() drain-and-reduce, the size flush, and the
    // timer-driven flush — so a drain never folds into a state that a concurrent flush is handing
    // to the flush pipeline. feed() stays outside: elements bind to a cycle when they are REDUCED,
    // not when they are fed, so feeding is a plain buffer push with nothing to race.
    private pumpLimit = pLimit(1)

    // Wakes a consumer that PARKS on next() instead of polling (see LIVENESS INVARIANT above).
    // With callEachBatchWhenEmpty the consumer never parks, so this is currently only consumed
    // via waitForActivity(); it is the liveness mechanism for a future wake-driven drain loop.
    private signal = new ResettableSignal()

    private readonly pipeline: ChunkPipeline<TRecordIn, TRecordOut, CRecordIn, CRecordOut, R>
    private readonly initialState: () => TState | Promise<TState>
    private readonly reduce: CycleReducer<TState, TRecordOut, CRecordOut, R>
    private readonly flushPipeline: ChunkPipeline<TState, TFlushOut, Record<string, never>, CFlushOut, R>
    private readonly shouldFlush: (state: TState) => boolean
    private readonly maxCycleAgeMs: number

    constructor(
        config: AccumulatingPipelineConfig<
            TRecordIn,
            TRecordOut,
            CRecordIn,
            CRecordOut,
            TState,
            TFlushOut,
            CFlushOut,
            R
        >
    ) {
        this.pipeline = config.pipeline
        this.initialState = config.initialState
        this.reduce = config.reduce
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
     * partial cycle is not lost on shutdown.
     */
    public stop(): Promise<AccumulatingResult<TFlushOut, CFlushOut, R> | null> {
        if (this.timer) {
            clearInterval(this.timer)
            this.timer = undefined
        }
        return this.pumpLimit(() => this.drainAndFlush())
    }

    private async drainAndFlush(): Promise<AccumulatingResult<TFlushOut, CFlushOut, R> | null> {
        // Drain any buffered record work into the state FIRST, so a revoke/stop flush covers
        // everything drained so far.
        const { sideEffects } = await this.drainRecord()
        const flushed = await this.flushNow()
        if (flushed === null) {
            return null
        }
        // Surface the record-phase side effects alongside the flush's, so the caller can make them
        // durable.
        return { ...flushed, sideEffects: [...sideEffects, ...flushed.sideEffects] }
    }

    /**
     * Feeds elements into the record pipeline. Elements bind to a cycle when their results are
     * reduced (inside next()/flush()), not when they are fed.
     */
    public feed(elements: OkResultWithContext<TRecordIn, CRecordIn>[]): void {
        this.pipeline.feed(elements)
    }

    public next(): Promise<AccumulatingResult<TFlushOut, CFlushOut, R> | null> {
        return this.pumpLimit(() => this.pump())
    }

    /**
     * Forces an immediate flush: drains any buffered record work into the state, then flushes.
     * The age timer keeps running. Used on Kafka partition revocation — rather than reaching into
     * the live cycle to discard the revoked partition, we process what we have and flush it.
     */
    public flush(): Promise<AccumulatingResult<TFlushOut, CFlushOut, R> | null> {
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

    private async pump(): Promise<AccumulatingResult<TFlushOut, CFlushOut, R> | null> {
        // Drain the record (main) pipeline first, folding its results into the cycle state.
        const { drained, sideEffects } = await this.drainRecord()
        if (drained > 0 || sideEffects.length > 0) {
            return { flushed: false, sideEffects }
        }

        // Main pipeline empty → flush on size or age.
        const sizeDue = this.currentState !== null && this.shouldFlush(this.currentState)
        if (this.flushDue || sizeDue) {
            return await this.flushNow()
        }

        return null
    }

    /**
     * Drains the record pipeline to null, handling each drained element exactly once: any side
     * effects still on its context are lifted into the turn (the caller makes them durable), and
     * the element is folded into the cycle state via `reduce` — then let go, so nothing beyond the
     * state is retained.
     */
    private async drainRecord(): Promise<{ drained: number; sideEffects: Promise<unknown>[] }> {
        let drained = 0
        const sideEffects: Promise<unknown>[] = []
        let result = await this.pipeline.next()
        while (result !== null) {
            if (result.length > 0) {
                let state = this.currentState ?? (await this.initialState())
                for (const element of result) {
                    sideEffects.push(...element.context.sideEffects)
                    state = await this.reduce(state, element)
                }
                this.currentState = state
                drained += result.length
            }
            result = await this.pipeline.next()
        }
        return { drained, sideEffects }
    }

    private async flushNow(): Promise<AccumulatingResult<TFlushOut, CFlushOut, R> | null> {
        this.flushDue = false
        this.rearmTimer()

        // Nothing was reduced this cycle — there is no state to flush.
        if (this.currentState === null) {
            return null
        }

        // Hand the flush pipeline one element: the cycle state. A fresh state is minted lazily
        // when the next cycle's first result is reduced.
        this.flushPipeline.feed([createOkContext(this.currentState, {})])
        this.currentState = null
        const elements = await this.drain(this.flushPipeline)
        // Aggregate any side effects the flush steps left on their results, so the caller can make
        // a flush-step produce durable.
        const sideEffects = elements.flatMap((element) => element.context.sideEffects)
        return { flushed: true, elements, sideEffects }
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
