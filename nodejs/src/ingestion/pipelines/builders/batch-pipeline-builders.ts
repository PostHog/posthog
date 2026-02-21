import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../../kafka/producer'
import { Team } from '../../../types'
import { PromiseScheduler } from '../../../utils/promise-scheduler'
import { BaseBatchPipeline, BatchProcessingStep } from '../base-batch-pipeline'
import { BatchPipeline } from '../batch-pipeline.interface'
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
 * Builder for configuring how items within a group are processed.
 */
export class GroupProcessingBuilder<TInput, TOutput, CInput = Record<string, never>, COutput = CInput, TKey = string> {
    constructor(
        private previousPipeline: BatchPipeline<TInput, TOutput, CInput, COutput>,
        private groupingFn: GroupingFunction<TOutput, TKey>
    ) {}

    /**
     * Process items within each group sequentially through the provided pipeline.
     */
    sequentially<U>(
        callback: (builder: StartPipelineBuilder<TOutput, COutput>) => PipelineBuilder<TOutput, U, COutput>
    ): BatchPipelineBuilder<TInput, U, CInput, COutput> {
        const processor = callback(new StartPipelineBuilder<TOutput, COutput>()).build()
        return new BatchPipelineBuilder(
            new ConcurrentlyGroupingBatchPipeline(this.groupingFn, processor, this.previousPipeline)
        )
    }
}

/**
 * Builder for grouped batch pipelines that allows configuring how groups are processed.
 */
export class GroupingBatchPipelineBuilder<TInput, TOutput, CInput, COutput, TKey> {
    constructor(
        private previousPipeline: BatchPipeline<TInput, TOutput, CInput, COutput>,
        private groupingFn: GroupingFunction<TOutput, TKey>
    ) {}

    /**
     * Process groups concurrently. Returns a builder to configure how items within each group are processed.
     * Results are returned unordered as each group completes.
     */
    concurrently<U>(
        callback: (
            builder: GroupProcessingBuilder<TInput, TOutput, CInput, COutput, TKey>
        ) => BatchPipelineBuilder<TInput, U, CInput, COutput>
    ): BatchPipelineBuilder<TInput, U, CInput, COutput> {
        return callback(new GroupProcessingBuilder(this.previousPipeline, this.groupingFn))
    }
}

export class BatchPipelineBuilder<TInput, TOutput, CInput, COutput = CInput> {
    constructor(protected pipeline: BatchPipeline<TInput, TOutput, CInput, COutput>) {}

    pipeBatch<U>(step: BatchProcessingStep<TOutput, U>): BatchPipelineBuilder<TInput, U, CInput, COutput> {
        return new BatchPipelineBuilder(new BaseBatchPipeline(step, this.pipeline))
    }

    concurrently<U>(
        callback: (builder: StartPipelineBuilder<TOutput, COutput>) => PipelineBuilder<TOutput, U, COutput>
    ): BatchPipelineBuilder<TInput, U, CInput, COutput> {
        const processor = callback(new StartPipelineBuilder<TOutput, COutput>()).build()
        return new BatchPipelineBuilder(new ConcurrentBatchProcessingPipeline(processor, this.pipeline))
    }

    pipeConcurrently<U>(processor: Pipeline<TOutput, U, COutput>): BatchPipelineBuilder<TInput, U, CInput, COutput> {
        return new BatchPipelineBuilder(new ConcurrentBatchProcessingPipeline(processor, this.pipeline))
    }

    sequentially<U>(
        callback: (builder: StartPipelineBuilder<TOutput, COutput>) => PipelineBuilder<TOutput, U, COutput>
    ): BatchPipelineBuilder<TInput, U, CInput, COutput> {
        const processor = callback(new StartPipelineBuilder<TOutput, COutput>()).build()
        return new BatchPipelineBuilder(new SequentialBatchPipeline(processor, this.pipeline))
    }

    gather(): BatchPipelineBuilder<TInput, TOutput, CInput, COutput> {
        return new BatchPipelineBuilder(new GatheringBatchPipeline(this.pipeline))
    }

    /**
     * Filters OK results, applies a mapping function, and processes through a subpipeline.
     * Non-OK results are passed through unchanged.
     *
     * @param mappingFn - Function to map OK results (transforms both value and context)
     * @param subpipelineCallback - Callback that receives a builder and returns the subpipeline
     */
    filterMap<TMapped, TSubOutput, CMapped = COutput, CSubOutput = CMapped>(
        mappingFn: FilterMapMappingFunction<TOutput, TMapped, COutput, CMapped>,
        subpipelineCallback: (
            builder: BatchPipelineBuilder<TMapped, TMapped, CMapped, CMapped>
        ) => BatchPipelineBuilder<TMapped, TSubOutput, CMapped, CSubOutput>
    ): BatchPipelineBuilder<TInput, TSubOutput, CInput, CSubOutput | COutput> {
        // Create a start builder for the subpipeline with the mapped types
        const startBuilder = new BatchPipelineBuilder(new BufferingBatchPipeline<TMapped, CMapped>())

        // Let the callback build the subpipeline
        const subpipelineBuilder = subpipelineCallback(startBuilder)
        const subPipeline = subpipelineBuilder.build()

        return new BatchPipelineBuilder(
            new FilterMapBatchPipeline<TInput, TOutput, TMapped, TSubOutput, CInput, COutput, CMapped, CSubOutput>(
                this.pipeline,
                mappingFn,
                subPipeline
            )
        )
    }

    groupBy<TKey>(
        groupingFn: GroupingFunction<TOutput, TKey>
    ): GroupingBatchPipelineBuilder<TInput, TOutput, CInput, COutput, TKey> {
        return new GroupingBatchPipelineBuilder(this.pipeline, groupingFn)
    }

    handleSideEffects(
        promiseScheduler: PromiseScheduler,
        options: { await: boolean }
    ): BatchPipelineBuilder<TInput, TOutput, CInput, COutput> {
        return new BatchPipelineBuilder(new SideEffectHandlingPipeline(this.pipeline, promiseScheduler, options))
    }

    messageAware<TOut, COut = COutput>(
        this: BatchPipelineBuilder<TInput, TOutput, CInput & { message: Message }, COutput & { message: Message }>,
        callback: (
            builder: BatchPipelineBuilder<
                TInput,
                TOutput,
                CInput & { message: Message },
                COutput & { message: Message }
            >
        ) => BatchPipelineBuilder<TInput, TOut, CInput & { message: Message }, COut & { message: Message }>
    ): MessageAwareBatchPipelineBuilder<TInput, TOut, CInput & { message: Message }, COut & { message: Message }> {
        const builtPipeline = callback(this)
        return new MessageAwareBatchPipelineBuilder(builtPipeline.build())
    }

    teamAware<TOut, COut = COutput>(
        this: BatchPipelineBuilder<TInput, TOutput, CInput & { team: Team }, COutput & { team: Team }>,
        callback: (
            builder: BatchPipelineBuilder<TInput, TOutput, CInput & { team: Team }, COutput & { team: Team }>
        ) => BatchPipelineBuilder<TInput, TOut, CInput & { team: Team }, COut & { team: Team }>
    ): TeamAwareBatchPipelineBuilder<TInput, TOut, CInput & { team: Team }, COut & { team: Team }> {
        const builtPipeline = callback(this)
        return new TeamAwareBatchPipelineBuilder(builtPipeline.build())
    }

    build(): BatchPipeline<TInput, TOutput, CInput, COutput> {
        return this.pipeline
    }
}

export class MessageAwareBatchPipelineBuilder<
    TInput,
    TOutput,
    CInput extends { message: Message },
    COutput extends { message: Message } = CInput,
> {
    constructor(protected pipeline: BatchPipeline<TInput, TOutput, CInput, COutput>) {}

    handleResults(config: PipelineConfig): ResultHandledBatchPipelineBuilder<TInput, TOutput, CInput, COutput> {
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
> {
    constructor(protected pipeline: BatchPipeline<TInput, TOutput, CInput, COutput>) {}

    handleSideEffects(
        promiseScheduler: PromiseScheduler,
        options: { await: boolean }
    ): BatchPipelineBuilder<TInput, TOutput, CInput, COutput> {
        return new BatchPipelineBuilder(new SideEffectHandlingPipeline(this.pipeline, promiseScheduler, options))
    }
}

export class TeamAwareBatchPipelineBuilder<
    TInput,
    TOutput,
    CInput extends { team: Team },
    COutput extends { team: Team },
> extends BatchPipelineBuilder<TInput, TOutput, CInput, COutput> {
    constructor(pipeline: BatchPipeline<TInput, TOutput, CInput, COutput>) {
        super(pipeline)
    }

    handleIngestionWarnings(
        kafkaProducer: KafkaProducerWrapper
    ): BatchPipelineBuilder<TInput, TOutput, CInput, COutput> {
        return new BatchPipelineBuilder(new IngestionWarningHandlingBatchPipeline(kafkaProducer, this.pipeline))
    }
}
