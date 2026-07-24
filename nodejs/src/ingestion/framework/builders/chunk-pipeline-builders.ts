import { Message } from 'node-rdkafka'

import { IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { BaseChunkPipeline, ChunkProcessingStep } from '~/ingestion/framework/base-chunk-pipeline'
import { BufferingChunkPipeline } from '~/ingestion/framework/buffering-chunk-pipeline'
import { ChunkPipeline } from '~/ingestion/framework/chunk-pipeline.interface'
import { ConcurrentChunkProcessingPipeline } from '~/ingestion/framework/concurrent-chunk-pipeline'
import {
    ConcurrentlyGroupingChunkPipeline,
    GroupingFunction,
} from '~/ingestion/framework/concurrently-grouping-chunk-pipeline'
import {
    FanInFunction,
    FanOutFanInChunkPipeline,
    FanOutFunction,
    FanOutSubContext,
} from '~/ingestion/framework/fan-out-fan-in-chunk-pipeline'
import { FilterMapChunkPipeline, FilterMapMappingFunction } from '~/ingestion/framework/filter-map-chunk-pipeline'
import { GatherOptions, GatheringChunkPipeline } from '~/ingestion/framework/gathering-chunk-pipeline'
import { IngestionWarningHandlingChunkPipeline } from '~/ingestion/framework/ingestion-warning-handling-chunk-pipeline'
import { Pipeline } from '~/ingestion/framework/pipeline.interface'
import { PipelineConfig, ResultHandlingPipeline } from '~/ingestion/framework/result-handling-pipeline'
import { RetryOptions, withChunkRetry } from '~/ingestion/framework/retry'
import { SequentialChunkPipeline } from '~/ingestion/framework/sequential-chunk-pipeline'
import { SideEffectHandlingPipeline } from '~/ingestion/framework/side-effect-handling-pipeline'

import { PipelineBuilder, StartPipelineBuilder } from './pipeline-builders'

/**
 * Minimal team context required for team-aware pipeline operations.
 * Only the team ID is needed to route warnings to the correct team.
 */
export interface TeamIdContext {
    team: { id: number }
}

/**
 * Configures how items within a group are processed. Groups produced by
 * `concurrentlyPerGroup` run concurrently; this builder's `sequentially` method
 * defines how the items within a single group are processed.
 */
export class GroupProcessingBuilder<
    TInput,
    TOutput,
    CInput = Record<string, never>,
    COutput = CInput,
    R extends string = never,
> {
    // Holds a completion function instead of the grouping function and previous
    // pipeline directly: a groupingFn field would be contravariant in TOutput,
    // making ChunkPipelineBuilder invariant in TOutput and breaking covariant
    // subpipeline callbacks (e.g. in newBatchingPipeline). In this closure's
    // signature TOutput only appears in variance-neutral positions.
    constructor(
        private readonly buildGroupedPipeline: <U, R2 extends string>(
            processor: Pipeline<TOutput, U, COutput, R2>
        ) => ChunkPipeline<TInput, U, CInput, COutput, R | R2>
    ) {}

    /**
     * Process the items within each group sequentially through the provided
     * pipeline: one item at a time, in input order. Groups still run
     * concurrently with respect to each other.
     */
    sequentially<U, R2 extends string = never>(
        callback: (builder: StartPipelineBuilder<TOutput, COutput>) => PipelineBuilder<TOutput, U, COutput, R2>
    ): ChunkPipelineBuilder<TInput, U, CInput, COutput, R | R2> {
        const processor = callback(new StartPipelineBuilder<TOutput, COutput>()).build()
        return new ChunkPipelineBuilder(this.buildGroupedPipeline(processor))
    }
}

/**
 * Middle stage of `.fanOut(fn).via(cb).fanIn(fn)`. Its only method is `via`,
 * so a fan-out stage cannot be built (or have results handled) until it is
 * closed with a subpipeline and a fan-in function.
 */
export class FanOutBuilder<
    TInput,
    TOutput,
    TSub,
    CInput = Record<string, never>,
    COutput = CInput,
    R extends string = never,
> {
    // Holds a completion function instead of the fan-out function and previous
    // pipeline directly, for the same variance reason as GroupProcessingBuilder:
    // in this closure's signature TOutput only appears in variance-neutral
    // positions, keeping ChunkPipelineBuilder covariant in TOutput.
    constructor(
        private readonly buildFannedOutPipeline: <TSubOut, U, RSub extends string>(
            subPipeline: ChunkPipeline<TSub, TSubOut, FanOutSubContext, FanOutSubContext, RSub>,
            fanInFn: FanInFunction<TOutput, TSubOut, U>
        ) => ChunkPipeline<TInput, U, CInput, COutput, R>
    ) {}

    /**
     * Route the sub-elements through a subpipeline built on the full chunk
     * builder surface (`concurrently` with `maxConcurrency`, per-step `retry`,
     * `concurrentlyPerGroup`, …). Sub-elements from all parents share the
     * subpipeline, so one concurrency cap governs the whole stage.
     *
     * Redirect sub-results never escape the stage, so the subpipeline's
     * redirect names (`RSub`) do not propagate to the stage's result type —
     * downstream `handleResults` won't demand outputs for redirects that
     * cannot happen. (A DLQ sub-result does surface, as the parent's
     * aggregated DLQ, which carries no redirect names.)
     */
    via<TSubOut, RSub extends string = never>(
        subpipelineCallback: (
            builder: ChunkPipelineBuilder<TSub, TSub, FanOutSubContext, FanOutSubContext>
        ) => ChunkPipelineBuilder<TSub, TSubOut, FanOutSubContext, FanOutSubContext, RSub>
    ): FanInBuilder<TInput, TOutput, TSubOut, CInput, COutput, R> {
        const startBuilder = new ChunkPipelineBuilder<TSub, TSub, FanOutSubContext, FanOutSubContext>(
            new BufferingChunkPipeline<TSub, FanOutSubContext>()
        )
        const subPipeline = subpipelineCallback(startBuilder).build()
        return new FanInBuilder(<U>(fanInFn: FanInFunction<TOutput, TSubOut, U>) =>
            this.buildFannedOutPipeline(subPipeline, fanInFn)
        )
    }
}

/**
 * Final stage of `.fanOut(fn).via(cb).fanIn(fn)`. Its only method is `fanIn`,
 * which folds the sub-results back into the parent and returns a regular
 * {@link ChunkPipelineBuilder}.
 */
export class FanInBuilder<
    TInput,
    TOutput,
    TSubOut,
    CInput = Record<string, never>,
    COutput = CInput,
    R extends string = never,
> {
    // Completion-closure shape for the same variance reason as FanOutBuilder.
    constructor(
        private readonly buildFannedInPipeline: <U>(
            fanInFn: FanInFunction<TOutput, TSubOut, U>
        ) => ChunkPipeline<TInput, U, CInput, COutput, R>
    ) {}

    /**
     * Close the stage: fold each parent's collected sub-results back into the
     * original element (synchronous, cheap).
     */
    fanIn<U>(fanInFn: FanInFunction<TOutput, TSubOut, U>): ChunkPipelineBuilder<TInput, U, CInput, COutput, R> {
        return new ChunkPipelineBuilder(this.buildFannedInPipeline(fanInFn))
    }
}

export class ChunkPipelineBuilder<TInput, TOutput, CInput, COutput = CInput, R extends string = never> {
    constructor(protected pipeline: ChunkPipeline<TInput, TOutput, CInput, COutput, R>) {}

    pipeChunk<U, R2 extends string = never>(
        step: ChunkProcessingStep<TOutput, U, R2>,
        options?: { retry?: RetryOptions }
    ): ChunkPipelineBuilder<TInput, U, CInput, COutput, R | R2> {
        const wrappedStep = options?.retry ? withChunkRetry(step, options.retry) : step
        return new ChunkPipelineBuilder(new BaseChunkPipeline(wrappedStep, this.pipeline))
    }

    /**
     * Process each item of the chunk concurrently, emitting results in input (FIFO) order.
     *
     * @param options.maxConcurrency - Cap on how many items process at once. Omitted means unbounded.
     */
    concurrently<U, R2 extends string = never>(
        callback: (builder: StartPipelineBuilder<TOutput, COutput>) => PipelineBuilder<TOutput, U, COutput, R2>,
        options?: { maxConcurrency?: number }
    ): ChunkPipelineBuilder<TInput, U, CInput, COutput, R | R2> {
        const processor = callback(new StartPipelineBuilder<TOutput, COutput>()).build()
        return new ChunkPipelineBuilder(
            new ConcurrentChunkProcessingPipeline(processor, this.pipeline, options?.maxConcurrency)
        )
    }

    sequentially<U, R2 extends string = never>(
        callback: (builder: StartPipelineBuilder<TOutput, COutput>) => PipelineBuilder<TOutput, U, COutput, R2>
    ): ChunkPipelineBuilder<TInput, U, CInput, COutput, R | R2> {
        const processor = callback(new StartPipelineBuilder<TOutput, COutput>()).build()
        return new ChunkPipelineBuilder(new SequentialChunkPipeline(processor, this.pipeline))
    }

    /**
     * Collect upstream chunks into larger ones. By default a barrier (drain
     * until empty, emit once); pass `{ maxWaitMs, minItems }` for a bounded
     * coalescer that never holds completed results behind in-flight work — see
     * {@link GatherOptions}.
     */
    gather(options?: GatherOptions): ChunkPipelineBuilder<TInput, TOutput, CInput, COutput, R> {
        if (this.pipeline instanceof GatheringChunkPipeline) {
            throw new Error('gather() cannot directly follow another gather() — merge them into a single call')
        }
        return new ChunkPipelineBuilder(new GatheringChunkPipeline(this.pipeline, options))
    }

    /**
     * Filters OK results, applies a mapping function, and processes through a subpipeline.
     * Non-OK results are passed through unchanged.
     *
     * @param mappingFn - Function to map OK results (transforms both value and context)
     * @param subpipelineCallback - Callback that receives a builder and returns the subpipeline
     */
    filterMap<TMapped, TSubOutput, CMapped = COutput, CSubOutput = CMapped, ROut extends string = never>(
        mappingFn: FilterMapMappingFunction<TOutput, TMapped, COutput, CMapped>,
        subpipelineCallback: (
            builder: ChunkPipelineBuilder<TMapped, TMapped, CMapped, CMapped>
        ) => ChunkPipelineBuilder<TMapped, TSubOutput, CMapped, CSubOutput, ROut>
    ): ChunkPipelineBuilder<TInput, TSubOutput, CInput, CSubOutput | COutput, R | ROut> {
        const startBuilder = new ChunkPipelineBuilder<TMapped, TMapped, CMapped, CMapped>(
            new BufferingChunkPipeline<TMapped, CMapped>()
        )
        const subpipelineBuilder = subpipelineCallback(startBuilder)
        const subPipeline = subpipelineBuilder.build()

        return new ChunkPipelineBuilder(
            new FilterMapChunkPipeline<
                TInput,
                TOutput,
                TMapped,
                TSubOutput,
                CInput,
                COutput,
                CMapped,
                CSubOutput,
                R,
                ROut
            >(this.pipeline, mappingFn, subPipeline)
        )
    }

    /**
     * Open a fan-out/fan-in stage: fan each OK element out into sub-elements,
     * process them through a subpipeline, and fan the results back into the
     * original element. The stage is staged so each part reads at the call
     * site — `.fanOut(fn).via((sub) => …).fanIn(fn)` — and only `.fanIn()`
     * closes it into a buildable pipeline.
     *
     * Cardinality is preserved at the parent level (N in, N out); parents emit
     * as they complete (unordered). Non-OK elements pass through unchanged.
     * OK sub-results are collected for the fan-in; dropped sub-elements are
     * silently excluded (DROP is the sanctioned way for a sub-step to discard
     * its sub-element); a DLQ sub-result fails the whole parent, which emits a
     * DLQ aggregating its sub DLQs instead of fanning in; REDIRECT sub-results
     * are excluded with a warning log — sub-elements are not Kafka messages.
     *
     * Like processing steps, the fan-out and fan-in functions are named
     * functions (defined in step files, created by factories where they need
     * config) — their `.name` is used for error attribution.
     *
     * @param fanOutFn - Splits an element into sub-elements (synchronous, cheap)
     */
    fanOut<TSub>(fanOutFn: FanOutFunction<TOutput, TSub>): FanOutBuilder<TInput, TOutput, TSub, CInput, COutput, R> {
        return new FanOutBuilder(
            <TSubOut, U, RSub extends string>(
                subPipeline: ChunkPipeline<TSub, TSubOut, FanOutSubContext, FanOutSubContext, RSub>,
                fanInFn: FanInFunction<TOutput, TSubOut, U>
            ) =>
                new FanOutFanInChunkPipeline<TInput, TOutput, TSub, TSubOut, U, CInput, COutput, R, RSub>(
                    this.pipeline,
                    fanOutFn,
                    subPipeline,
                    fanInFn
                )
        )
    }

    /**
     * Group items by key and process the groups concurrently, optionally capped
     * by `maxConcurrency`. Results are returned unordered as each group completes.
     *
     * The callback receives a group builder whose only method, `sequentially`,
     * configures how items WITHIN a group are processed. Making that step explicit
     * keeps within-group ordering visible at the call site.
     *
     * @param options.maxConcurrency - Cap on how many groups process at once. Omitted means unbounded.
     */
    concurrentlyPerGroup<TKey, U, ROut extends string = never>(
        groupingFn: GroupingFunction<TOutput, TKey>,
        callback: (
            group: GroupProcessingBuilder<TInput, TOutput, CInput, COutput, R>
        ) => ChunkPipelineBuilder<TInput, U, CInput, COutput, ROut>,
        options?: { maxConcurrency?: number }
    ): ChunkPipelineBuilder<TInput, U, CInput, COutput, R | ROut> {
        return callback(
            new GroupProcessingBuilder(
                <U2, R2 extends string>(processor: Pipeline<TOutput, U2, COutput, R2>) =>
                    new ConcurrentlyGroupingChunkPipeline(groupingFn, processor, this.pipeline, options?.maxConcurrency)
            )
        )
    }

    handleSideEffects(
        promiseScheduler: PromiseScheduler,
        options: { await: boolean }
    ): ChunkPipelineBuilder<TInput, TOutput, CInput, COutput, R> {
        return new ChunkPipelineBuilder(new SideEffectHandlingPipeline(this.pipeline, promiseScheduler, options))
    }

    messageAware<TOut, COut = COutput, ROut extends string = never>(
        this: ChunkPipelineBuilder<TInput, TOutput, CInput & { message: Message }, COutput & { message: Message }, R>,
        callback: (
            builder: ChunkPipelineBuilder<
                TInput,
                TOutput,
                CInput & { message: Message },
                COutput & { message: Message },
                R
            >
        ) => ChunkPipelineBuilder<TInput, TOut, CInput & { message: Message }, COut & { message: Message }, ROut>
    ): MessageAwareChunkPipelineBuilder<
        TInput,
        TOut,
        CInput & { message: Message },
        COut & { message: Message },
        ROut
    > {
        const builtPipeline = callback(this)
        return new MessageAwareChunkPipelineBuilder(builtPipeline.build())
    }

    teamAware<TOut, COut = COutput, ROut extends string = never>(
        this: ChunkPipelineBuilder<TInput, TOutput, CInput & TeamIdContext, COutput & TeamIdContext, R>,
        callback: (
            builder: ChunkPipelineBuilder<TInput, TOutput, CInput & TeamIdContext, COutput & TeamIdContext, R>
        ) => ChunkPipelineBuilder<TInput, TOut, CInput & TeamIdContext, COut & TeamIdContext, ROut>
    ): TeamAwareChunkPipelineBuilder<TInput, TOut, CInput & TeamIdContext, COut & TeamIdContext, ROut> {
        const builtPipeline = callback(this)
        return new TeamAwareChunkPipelineBuilder(builtPipeline.build())
    }

    build(): ChunkPipeline<TInput, TOutput, CInput, COutput, R> {
        return this.pipeline
    }
}

export class MessageAwareChunkPipelineBuilder<
    TInput,
    TOutput,
    CInput extends { message: Message },
    COutput extends { message: Message } = CInput,
    R extends string = never,
> {
    constructor(protected pipeline: ChunkPipeline<TInput, TOutput, CInput, COutput, R>) {}

    handleResults<RConfig extends string = never>(
        config: PipelineConfig<R | RConfig>
    ): ResultHandledChunkPipelineBuilder<TInput, TOutput, CInput, COutput, R> {
        return new ResultHandledChunkPipelineBuilder(new ResultHandlingPipeline(this.pipeline, config))
    }
}

/**
 * Builder returned after handleResults(). Only allows handleSideEffects() to be called,
 * enforcing that side effects must be handled before building.
 */
export class ResultHandledChunkPipelineBuilder<
    TInput,
    TOutput,
    CInput extends { message: Message },
    COutput extends { message: Message } = CInput,
    R extends string = never,
> {
    constructor(protected pipeline: ChunkPipeline<TInput, TOutput, CInput, COutput, R>) {}

    handleSideEffects(
        promiseScheduler: PromiseScheduler,
        options: { await: boolean }
    ): ChunkPipelineBuilder<TInput, TOutput, CInput, COutput, R> {
        return new ChunkPipelineBuilder(new SideEffectHandlingPipeline(this.pipeline, promiseScheduler, options))
    }
}

export class TeamAwareChunkPipelineBuilder<
    TInput,
    TOutput,
    CInput extends TeamIdContext,
    COutput extends TeamIdContext,
    R extends string = never,
> extends ChunkPipelineBuilder<TInput, TOutput, CInput, COutput, R> {
    constructor(pipeline: ChunkPipeline<TInput, TOutput, CInput, COutput, R>) {
        super(pipeline)
    }

    handleIngestionWarnings(
        outputs: IngestionOutputs<IngestionWarningsOutput>
    ): ChunkPipelineBuilder<TInput, TOutput, CInput, COutput, R> {
        return new ChunkPipelineBuilder(new IngestionWarningHandlingChunkPipeline(outputs, this.pipeline))
    }
}
