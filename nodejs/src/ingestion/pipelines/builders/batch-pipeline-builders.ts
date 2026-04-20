import { Message } from 'node-rdkafka'

import { PromiseScheduler } from '../../../utils/promise-scheduler'
import { IngestionWarningsOutput } from '../../common/outputs'
import { IngestionOutputs } from '../../outputs/ingestion-outputs'
import { BaseBatchPipeline, BatchProcessingStep } from '../base-batch-pipeline'
import { BatchPipeline } from '../batch-pipeline.interface'
import { BatchRetryOptions, withBatchRetry } from '../batch-retry'
import { BufferingBatchPipeline } from '../buffering-batch-pipeline'
import { ConcurrentBatchProcessingPipeline } from '../concurrent-batch-pipeline'
import { ConcurrentlyGroupingBatchPipeline, GroupingFunction } from '../concurrently-grouping-batch-pipeline'
import { FilterMapBatchPipeline, FilterMapMappingFunction } from '../filter-map-batch-pipeline'
import { GatheringBatchPipeline } from '../gathering-batch-pipeline'
import { IngestionWarningHandlingBatchPipeline } from '../ingestion-warning-handling-batch-pipeline'
import { Pipeline } from '../pipeline.interface'
import { PipelineConfig, ResultHandlingPipeline } from '../result-handling-pipeline'
import { SequentialBatchPipeline } from '../sequential-batch-pipeline'
import { SideEffectHandlingPipeline } from '../side-effect-handling-pipeline'
import { PipelineBuilder, StartPipelineBuilder } from './pipeline-builders'

/**
 * Minimal team context required for team-aware pipeline operations.
 * Only the team ID is needed to route warnings to the correct team.
 */
export interface TeamIdContext {
    team: { id: number }
}

/**
 * Builder for configuring how items within a group are processed.
 */
export class GroupProcessingBuilder<
    TInput,
    TOutput,
    CInput = Record<string, never>,
    COutput = CInput,
    TKey = string,
    R extends string = never,
> {
    constructor(
        private previousPipeline: BatchPipeline<TInput, TOutput, CInput, COutput, R>,
        private groupingFn: GroupingFunction<TOutput, TKey>
    ) {}

    /**
     * Process items within each group sequentially through the provided pipeline.
     */
    sequentially<U, R2 extends string = never>(
        callback: (builder: StartPipelineBuilder<TOutput, COutput>) => PipelineBuilder<TOutput, U, COutput, R2>
    ): BatchPipelineBuilder<TInput, U, CInput, COutput, R | R2> {
        const processor = callback(new StartPipelineBuilder<TOutput, COutput>()).build()
        return new BatchPipelineBuilder(
            new ConcurrentlyGroupingBatchPipeline(this.groupingFn, processor, this.previousPipeline)
        )
    }
}

/**
 * Builder for grouped batch pipelines that allows configuring how groups are processed.
 */
export class GroupingBatchPipelineBuilder<TInput, TOutput, CInput, COutput, TKey, R extends string = never> {
    constructor(
        private previousPipeline: BatchPipeline<TInput, TOutput, CInput, COutput, R>,
        private groupingFn: GroupingFunction<TOutput, TKey>
    ) {}

    /**
     * Process groups concurrently. Returns a builder to configure how items within each group are processed.
     * Results are returned unordered as each group completes.
     */
    concurrently<U, ROut extends string = never>(
        callback: (
            builder: GroupProcessingBuilder<TInput, TOutput, CInput, COutput, TKey, R>
        ) => BatchPipelineBuilder<TInput, U, CInput, COutput, ROut>
    ): BatchPipelineBuilder<TInput, U, CInput, COutput, R | ROut> {
        return callback(new GroupProcessingBuilder(this.previousPipeline, this.groupingFn))
    }
}

export class BatchPipelineBuilder<TInput, TOutput, CInput, COutput = CInput, R extends string = never> {
    constructor(protected pipeline: BatchPipeline<TInput, TOutput, CInput, COutput, R>) {}

    pipeBatch<U, R2 extends string = never>(
        step: BatchProcessingStep<TOutput, U, R2>
    ): BatchPipelineBuilder<TInput, U, CInput, COutput, R | R2> {
        return new BatchPipelineBuilder(new BaseBatchPipeline(step, this.pipeline))
    }

    /**
     * Add a batch processing step with automatic retry logic.
     *
     * When the step throws a retriable error (error.isRetriable === true),
     * it will be retried with exponential backoff. Non-retriable errors
     * are converted to DLQ results for all inputs in the batch.
     */
    pipeBatchWithRetry<U, R2 extends string = never>(
        step: BatchProcessingStep<TOutput, U, R2>,
        options?: BatchRetryOptions
    ): BatchPipelineBuilder<TInput, U, CInput, COutput, R | R2> {
        return this.pipeBatch(withBatchRetry(step, options))
    }

    concurrently<U, R2 extends string = never>(
        callback: (builder: StartPipelineBuilder<TOutput, COutput>) => PipelineBuilder<TOutput, U, COutput, R2>
    ): BatchPipelineBuilder<TInput, U, CInput, COutput, R | R2> {
        const processor = callback(new StartPipelineBuilder<TOutput, COutput>()).build()
        return new BatchPipelineBuilder(new ConcurrentBatchProcessingPipeline(processor, this.pipeline))
    }

    pipeConcurrently<U, R2 extends string = never>(
        processor: Pipeline<TOutput, U, COutput, R2>
    ): BatchPipelineBuilder<TInput, U, CInput, COutput, R | R2> {
        return new BatchPipelineBuilder(new ConcurrentBatchProcessingPipeline(processor, this.pipeline))
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

    groupBy<TKey>(
        groupingFn: GroupingFunction<TOutput, TKey>
    ): GroupingBatchPipelineBuilder<TInput, TOutput, CInput, COutput, TKey, R> {
        return new GroupingBatchPipelineBuilder(this.pipeline, groupingFn)
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
