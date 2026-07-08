import { Message } from 'node-rdkafka'

import { IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { BaseBatchPipeline, BatchProcessingStep } from '~/ingestion/framework/base-batch-pipeline'
import { BatchPipeline } from '~/ingestion/framework/batch-pipeline.interface'
import { BufferingBatchPipeline } from '~/ingestion/framework/buffering-batch-pipeline'
import { ConcurrentBatchProcessingPipeline } from '~/ingestion/framework/concurrent-batch-pipeline'
import {
    ConcurrentlyGroupingBatchPipeline,
    GroupingFunction,
} from '~/ingestion/framework/concurrently-grouping-batch-pipeline'
import { FilterMapBatchPipeline, FilterMapMappingFunction } from '~/ingestion/framework/filter-map-batch-pipeline'
import { GatheringBatchPipeline } from '~/ingestion/framework/gathering-batch-pipeline'
import { IngestionWarningHandlingBatchPipeline } from '~/ingestion/framework/ingestion-warning-handling-batch-pipeline'
import { Pipeline } from '~/ingestion/framework/pipeline.interface'
import { PipelineConfig, ResultHandlingPipeline } from '~/ingestion/framework/result-handling-pipeline'
import { RetryOptions, withBatchRetry } from '~/ingestion/framework/retry'
import { SequentialBatchPipeline } from '~/ingestion/framework/sequential-batch-pipeline'
import { SideEffectHandlingPipeline } from '~/ingestion/framework/side-effect-handling-pipeline'

import { PipelineBuilder, StartPipelineBuilder } from './pipeline-builders'

/**
 * Minimal team context required for team-aware pipeline operations.
 * Only the team ID is needed to route warnings to the correct team.
 */
export interface TeamIdContext {
    team: { id: number }
}

export class BatchPipelineBuilder<TInput, TOutput, CInput, COutput = CInput, R extends string = never> {
    constructor(protected pipeline: BatchPipeline<TInput, TOutput, CInput, COutput, R>) {}

    pipeBatch<U, R2 extends string = never>(
        step: BatchProcessingStep<TOutput, U, R2>,
        options?: { retry?: RetryOptions }
    ): BatchPipelineBuilder<TInput, U, CInput, COutput, R | R2> {
        const wrappedStep = options?.retry ? withBatchRetry(step, options.retry) : step
        return new BatchPipelineBuilder(new BaseBatchPipeline(wrappedStep, this.pipeline))
    }

    /**
     * Process each item of the batch concurrently, emitting results in input (FIFO) order.
     *
     * @param options.maxConcurrency - Cap on how many items process at once. Omitted means unbounded.
     */
    concurrently<U, R2 extends string = never>(
        callback: (builder: StartPipelineBuilder<TOutput, COutput>) => PipelineBuilder<TOutput, U, COutput, R2>,
        options?: { maxConcurrency?: number }
    ): BatchPipelineBuilder<TInput, U, CInput, COutput, R | R2> {
        const processor = callback(new StartPipelineBuilder<TOutput, COutput>()).build()
        return new BatchPipelineBuilder(
            new ConcurrentBatchProcessingPipeline(processor, this.pipeline, options?.maxConcurrency)
        )
    }

    pipeConcurrently<U, R2 extends string = never>(
        processor: Pipeline<TOutput, U, COutput, R2>,
        options?: { maxConcurrency?: number }
    ): BatchPipelineBuilder<TInput, U, CInput, COutput, R | R2> {
        return new BatchPipelineBuilder(
            new ConcurrentBatchProcessingPipeline(processor, this.pipeline, options?.maxConcurrency)
        )
    }

    sequentially<U, R2 extends string = never>(
        callback: (builder: StartPipelineBuilder<TOutput, COutput>) => PipelineBuilder<TOutput, U, COutput, R2>
    ): BatchPipelineBuilder<TInput, U, CInput, COutput, R | R2> {
        const processor = callback(new StartPipelineBuilder<TOutput, COutput>()).build()
        return new BatchPipelineBuilder(new SequentialBatchPipeline(processor, this.pipeline))
    }

    gather(): BatchPipelineBuilder<TInput, TOutput, CInput, COutput, R> {
        return new BatchPipelineBuilder(new GatheringBatchPipeline(this.pipeline))
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
            builder: BatchPipelineBuilder<TMapped, TMapped, CMapped, CMapped>
        ) => BatchPipelineBuilder<TMapped, TSubOutput, CMapped, CSubOutput, ROut>
    ): BatchPipelineBuilder<TInput, TSubOutput, CInput, CSubOutput | COutput, R | ROut> {
        const startBuilder = new BatchPipelineBuilder<TMapped, TMapped, CMapped, CMapped>(
            new BufferingBatchPipeline<TMapped, CMapped>()
        )
        const subpipelineBuilder = subpipelineCallback(startBuilder)
        const subPipeline = subpipelineBuilder.build()

        return new BatchPipelineBuilder(
            new FilterMapBatchPipeline<
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
     * Group items by key and process the groups concurrently; items within a
     * group are processed sequentially through the provided pipeline.
     * Results are returned unordered as each group completes.
     *
     * @param options.maxConcurrency - Cap on how many groups process at once. Omitted means unbounded.
     */
    concurrentlyPerGroup<TKey, U, R2 extends string = never>(
        groupingFn: GroupingFunction<TOutput, TKey>,
        callback: (builder: StartPipelineBuilder<TOutput, COutput>) => PipelineBuilder<TOutput, U, COutput, R2>,
        options?: { maxConcurrency?: number }
    ): BatchPipelineBuilder<TInput, U, CInput, COutput, R | R2> {
        const processor = callback(new StartPipelineBuilder<TOutput, COutput>()).build()
        return new BatchPipelineBuilder(
            new ConcurrentlyGroupingBatchPipeline(groupingFn, processor, this.pipeline, options?.maxConcurrency)
        )
    }

    handleSideEffects(
        promiseScheduler: PromiseScheduler,
        options: { await: boolean }
    ): BatchPipelineBuilder<TInput, TOutput, CInput, COutput, R> {
        return new BatchPipelineBuilder(new SideEffectHandlingPipeline(this.pipeline, promiseScheduler, options))
    }

    messageAware<TOut, COut = COutput, ROut extends string = never>(
        this: BatchPipelineBuilder<TInput, TOutput, CInput & { message: Message }, COutput & { message: Message }, R>,
        callback: (
            builder: BatchPipelineBuilder<
                TInput,
                TOutput,
                CInput & { message: Message },
                COutput & { message: Message },
                R
            >
        ) => BatchPipelineBuilder<TInput, TOut, CInput & { message: Message }, COut & { message: Message }, ROut>
    ): MessageAwareBatchPipelineBuilder<
        TInput,
        TOut,
        CInput & { message: Message },
        COut & { message: Message },
        ROut
    > {
        const builtPipeline = callback(this)
        return new MessageAwareBatchPipelineBuilder(builtPipeline.build())
    }

    teamAware<TOut, COut = COutput, ROut extends string = never>(
        this: BatchPipelineBuilder<TInput, TOutput, CInput & TeamIdContext, COutput & TeamIdContext, R>,
        callback: (
            builder: BatchPipelineBuilder<TInput, TOutput, CInput & TeamIdContext, COutput & TeamIdContext, R>
        ) => BatchPipelineBuilder<TInput, TOut, CInput & TeamIdContext, COut & TeamIdContext, ROut>
    ): TeamAwareBatchPipelineBuilder<TInput, TOut, CInput & TeamIdContext, COut & TeamIdContext, ROut> {
        const builtPipeline = callback(this)
        return new TeamAwareBatchPipelineBuilder(builtPipeline.build())
    }

    build(): BatchPipeline<TInput, TOutput, CInput, COutput, R> {
        return this.pipeline
    }
}

export class MessageAwareBatchPipelineBuilder<
    TInput,
    TOutput,
    CInput extends { message: Message },
    COutput extends { message: Message } = CInput,
    R extends string = never,
> {
    constructor(protected pipeline: BatchPipeline<TInput, TOutput, CInput, COutput, R>) {}

    handleResults<RConfig extends string = never>(
        config: PipelineConfig<R | RConfig>
    ): ResultHandledBatchPipelineBuilder<TInput, TOutput, CInput, COutput, R> {
        return new ResultHandledBatchPipelineBuilder(new ResultHandlingPipeline(this.pipeline, config))
    }
}

/**
 * Builder returned after handleResults(). Only allows handleSideEffects() to be called,
 * enforcing that side effects must be handled before building.
 */
export class ResultHandledBatchPipelineBuilder<
    TInput,
    TOutput,
    CInput extends { message: Message },
    COutput extends { message: Message } = CInput,
    R extends string = never,
> {
    constructor(protected pipeline: BatchPipeline<TInput, TOutput, CInput, COutput, R>) {}

    handleSideEffects(
        promiseScheduler: PromiseScheduler,
        options: { await: boolean }
    ): BatchPipelineBuilder<TInput, TOutput, CInput, COutput, R> {
        return new BatchPipelineBuilder(new SideEffectHandlingPipeline(this.pipeline, promiseScheduler, options))
    }
}

export class TeamAwareBatchPipelineBuilder<
    TInput,
    TOutput,
    CInput extends TeamIdContext,
    COutput extends TeamIdContext,
    R extends string = never,
> extends BatchPipelineBuilder<TInput, TOutput, CInput, COutput, R> {
    constructor(pipeline: BatchPipeline<TInput, TOutput, CInput, COutput, R>) {
        super(pipeline)
    }

    handleIngestionWarnings(
        outputs: IngestionOutputs<IngestionWarningsOutput>
    ): BatchPipelineBuilder<TInput, TOutput, CInput, COutput, R> {
        return new BatchPipelineBuilder(new IngestionWarningHandlingBatchPipeline(outputs, this.pipeline))
    }
}
