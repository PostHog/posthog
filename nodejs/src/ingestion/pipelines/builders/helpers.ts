import {
    AfterBatchInput,
    AfterBatchOutput,
    BatchingContext,
    BatchingPipeline,
    BatchingPipelineOptions,
    BeforeBatchInput,
    BeforeBatchOutput,
} from '../batching-pipeline'
import { BufferingBatchPipeline } from '../buffering-batch-pipeline'
import { BatchPipelineBuilder } from './batch-pipeline-builders'
import { PipelineBuilder, StartPipelineBuilder } from './pipeline-builders'

export function newBatchPipelineBuilder<T, C = Record<string, never>>(): BatchPipelineBuilder<T, T, C> {
    return new BatchPipelineBuilder(new BufferingBatchPipeline<T, C>())
}

export function newPipelineBuilder<T, C = Record<string, never>>(): StartPipelineBuilder<T, C> {
    return new StartPipelineBuilder<T, C>()
}

export function newBatchingPipeline<TInput, TOutput, CInput, CBatch = Record<string, never>, COutput = CInput>(
    beforeBatch: (
        builder: StartPipelineBuilder<BeforeBatchInput<TInput, CInput>, Record<string, never>>
    ) => PipelineBuilder<
        BeforeBatchInput<TInput, CInput>,
        BeforeBatchOutput<TInput, CInput, CBatch>,
        Record<string, never>
    >,
    callback: (
        builder: BatchPipelineBuilder<TInput, TInput, CInput & BatchingContext, CInput & BatchingContext>
    ) => BatchPipelineBuilder<TInput, TOutput, CInput & BatchingContext, COutput & BatchingContext>,
    afterBatch: (
        builder: StartPipelineBuilder<
            AfterBatchInput<TOutput, COutput & BatchingContext, CBatch>,
            Record<string, never>
        >
    ) => PipelineBuilder<
        AfterBatchInput<TOutput, COutput & BatchingContext, CBatch>,
        AfterBatchOutput<TOutput, COutput & BatchingContext, CBatch>,
        Record<string, never>
    >,
    options?: Partial<BatchingPipelineOptions>
): BatchingPipeline<TInput, TOutput, CInput, CBatch, CInput & BatchingContext, COutput & BatchingContext> {
    const startBuilder = new BatchPipelineBuilder(new BufferingBatchPipeline<TInput, CInput & BatchingContext>())
    const subPipeline = callback(startBuilder).build()

    const beforePipeline = beforeBatch(
        new StartPipelineBuilder<BeforeBatchInput<TInput, CInput>, Record<string, never>>()
    ).build()

    const afterPipeline = afterBatch(
        new StartPipelineBuilder<AfterBatchInput<TOutput, COutput & BatchingContext, CBatch>, Record<string, never>>()
    ).build()

    return new BatchingPipeline(subPipeline, beforePipeline, afterPipeline, options)
}
