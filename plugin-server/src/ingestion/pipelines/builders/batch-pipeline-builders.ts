import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../../kafka/producer'
import { Team } from '../../../types'
import { PromiseScheduler } from '../../../utils/promise-scheduler'
import { BaseBatchPipeline, BatchProcessingStep } from '../base-batch-pipeline'
import { BatchPipeline } from '../batch-pipeline.interface'
import { BufferingBatchPipeline } from '../buffering-batch-pipeline'
import { ConcurrentBatchProcessingPipeline } from '../concurrent-batch-pipeline'
import { FilterOkBatchPipeline } from '../filter-ok-batch-pipeline'
import { GatheringBatchPipeline } from '../gathering-batch-pipeline'
import { IngestionWarningHandlingBatchPipeline } from '../ingestion-warning-handling-batch-pipeline'
import { MappingBatchPipeline, MappingFunction } from '../mapping-batch-pipeline'
import { Pipeline } from '../pipeline.interface'
import { PipelineConfig, ResultHandlingPipeline } from '../result-handling-pipeline'
import { SequentialBatchPipeline } from '../sequential-batch-pipeline'
import { ShardingBatchPipeline, ShardingFunction } from '../sharding-batch-pipeline'
import { SideEffectHandlingPipeline } from '../side-effect-handling-pipeline'
import { PipelineBuilder, StartPipelineBuilder } from './pipeline-builders'

export class FilteredBatchPipelineBuilder<TInput, TOutput, CInput, COutput> {
    constructor(private filteredPipeline: FilterOkBatchPipeline<TInput, TOutput, CInput, COutput>) {}

    map<TMapped, CMapped = COutput>(
        mappingFn: MappingFunction<TOutput, TMapped, COutput, CMapped>
    ): BatchPipelineBuilder<TInput, TMapped, CInput, CMapped> {
        return new BatchPipelineBuilder(
            new MappingBatchPipeline<TInput, TOutput, TMapped, CInput, COutput, CMapped>(
                this.filteredPipeline,
                mappingFn
            )
        )
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

    sharding<U>(
        shardingFn: ShardingFunction<TOutput, COutput>,
        numShards: number,
        callback: (
            builder: BatchPipelineBuilder<TOutput, TOutput, COutput, COutput>
        ) => BatchPipelineBuilder<TOutput, U, COutput, COutput>
    ): BatchPipelineBuilder<TInput, U, CInput, COutput> {
        const shardPipelines: BatchPipeline<TOutput, U, COutput, COutput>[] = []
        for (let i = 0; i < numShards; i++) {
            const shardPipeline = callback(
                new BatchPipelineBuilder(new BufferingBatchPipeline<TOutput, COutput>())
            ).build()
            shardPipelines.push(shardPipeline)
        }
        return new BatchPipelineBuilder(new ShardingBatchPipeline(shardingFn, shardPipelines, this.pipeline))
    }

    gather(): BatchPipelineBuilder<TInput, TOutput, CInput, COutput> {
        return new BatchPipelineBuilder(new GatheringBatchPipeline(this.pipeline))
    }

    filterOk(): FilteredBatchPipelineBuilder<TInput, TOutput, CInput, COutput> {
        return new FilteredBatchPipelineBuilder(new FilterOkBatchPipeline(this.pipeline))
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

    handleResults(config: PipelineConfig): BatchPipelineBuilder<TInput, TOutput, CInput, COutput> {
        return new BatchPipelineBuilder(new ResultHandlingPipeline(this.pipeline, config))
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
