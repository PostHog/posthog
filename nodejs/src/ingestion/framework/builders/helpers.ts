import {
    AfterBatchInput,
    AfterBatchOutput,
    BatchingContext,
    BatchingPipeline,
    BatchingPipelineOptions,
    BeforeBatchInput,
    BeforeBatchOutput,
} from '~/ingestion/framework/batching-pipeline'
import { BufferingChunkPipeline } from '~/ingestion/framework/buffering-chunk-pipeline'
import { DebugContextOf, PipelineBuilderContext } from '~/ingestion/framework/pipeline.interface'

import { ChunkPipelineBuilder } from './chunk-pipeline-builders'
import { PipelineBuilder, StartPipelineBuilder } from './pipeline-builders'

export function newChunkPipelineBuilder<T, C = Record<string, never>>(
    builderContext?: PipelineBuilderContext<DebugContextOf<C>>
): ChunkPipelineBuilder<T, T, C, C, never, DebugContextOf<C>> {
    return new ChunkPipelineBuilder(new BufferingChunkPipeline<T, C>(), builderContext)
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
    D = DebugContextOf<CInput>,
>(
    beforeBatch: (
        builder: StartPipelineBuilder<BeforeBatchInput<TInput, CInput>, Record<string, never>>
    ) => PipelineBuilder<
        BeforeBatchInput<TInput, CInput>,
        BeforeBatchOutput<TInput, CInput, CBatch>,
        Record<string, never>
    >,
    callback: (
        builder: ChunkPipelineBuilder<
            TInput & CBatch,
            TInput & CBatch,
            CInput & BatchingContext,
            CInput & BatchingContext,
            never,
            D
        >
    ) => ChunkPipelineBuilder<TInput & CBatch, TOutput, CInput & BatchingContext, COutput & BatchingContext, R, D>,
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
    options?: Partial<BatchingPipelineOptions>,
    builderContext?: PipelineBuilderContext<D>
): BatchingPipeline<TInput, TOutput, CInput, CBatch, COutput & BatchingContext, R> {
    const startBuilder = new ChunkPipelineBuilder<
        TInput & CBatch,
        TInput & CBatch,
        CInput & BatchingContext,
        CInput & BatchingContext,
        never,
        D
    >(new BufferingChunkPipeline<TInput & CBatch, CInput & BatchingContext>(), builderContext)
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
