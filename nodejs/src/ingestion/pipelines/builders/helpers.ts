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

export function newBatchingPipeline<
    TInput,
    TOutput,
    CInput,
    CBatch = NonNullable<unknown>,
    COutput = CInput,
    R extends string = never,
>(
    beforeBatch: (
        builder: StartPipelineBuilder<BeforeBatchInput<TInput, CInput>, Record<string, never>>
    ) => PipelineBuilder<
        BeforeBatchInput<TInput, CInput>,
        BeforeBatchOutput<TInput, CInput, CBatch>,
        Record<string, never>
    >,
    callback: (
        builder: BatchPipelineBuilder<
            TInput & CBatch,
            TInput & CBatch,
            CInput & BatchingContext,
            CInput & BatchingContext
        >
    ) => BatchPipelineBuilder<TInput & CBatch, TOutput, CInput & BatchingContext, COutput & BatchingContext, R>,
    afterBatch: (
        builder: StartPipelineBuilder<
            AfterBatchInput<TOutput, COutput & BatchingContext, CBatch, R>,
            Record<string, never>
        >
    ) => PipelineBuilder<
        AfterBatchInput<TOutput, COutput & BatchingContext, CBatch, R>,
        AfterBatchOutput<TOutput, COutput & BatchingContext, CBatch, R>,
        Record<string, never>
    >,
    options?: Partial<BatchingPipelineOptions>
): BatchingPipeline<TInput, TOutput, CInput, CBatch, COutput & BatchingContext, R> {
    const startBuilder = new BatchPipelineBuilder(
        new BufferingBatchPipeline<TInput & CBatch, CInput & BatchingContext>()
    )
    const subPipeline = callback(startBuilder).build()

    const beforePipeline = beforeBatch(
        new StartPipelineBuilder<BeforeBatchInput<TInput, CInput>, Record<string, never>>()
    ).build()

    const afterPipeline = afterBatch(
        new StartPipelineBuilder<
            AfterBatchInput<TOutput, COutput & BatchingContext, CBatch, R>,
            Record<string, never>
        >()
    ).build()

    return new BatchingPipeline(subPipeline, beforePipeline, afterPipeline, options)
}
