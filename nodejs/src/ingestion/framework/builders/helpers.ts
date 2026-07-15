import { AccumulatingPipeline, CycleReducer } from '~/ingestion/framework/accumulating-pipeline'
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
import { ChunkPipeline } from '~/ingestion/framework/chunk-pipeline.interface'

import { ChunkPipelineBuilder } from './chunk-pipeline-builders'
import { PipelineBuilder, StartPipelineBuilder } from './pipeline-builders'

export function newChunkPipelineBuilder<T, C = Record<string, never>>(): ChunkPipelineBuilder<T, T, C> {
    return new ChunkPipelineBuilder(new BufferingChunkPipeline<T, C>())
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
        builder: ChunkPipelineBuilder<
            TInput & CBatch,
            TInput & CBatch,
            CInput & BatchingContext,
            CInput & BatchingContext
        >
    ) => ChunkPipelineBuilder<TInput & CBatch, TOutput, CInput & BatchingContext, COutput & BatchingContext, R>,
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
    const startBuilder = new ChunkPipelineBuilder(
        new BufferingChunkPipeline<TInput & CBatch, CInput & BatchingContext>()
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

/**
 * Builder-style constructor for AccumulatingPipeline, mirroring newBatchingPipeline: `flush` is a
 * builder callback that gets `.build()`-ed for you. The record `pipeline` is passed pre-built,
 * since deployments choose it (e.g. the default vs ML-mirror session replay pipeline).
 */
export function newAccumulatingPipeline<
    TRecordIn, // element fed in per message
    TRecordOut, // element out of the per-message pipeline; reduced into the cycle state
    CRecordIn, // per-message pipeline context in
    CRecordOut, // per-message pipeline context out (readable in the reducer, then let go)
    TState, // cycle state: the one accumulator everything folds into
    TFlushOut, // element out of the flush pipeline
    CFlushOut = Record<string, never>, // flush-pipeline context out
    R extends string = never, // redirect output names this pipeline can emit
>(config: {
    /** Pre-built record pipeline (a plain chunk pipeline); it never sees the cycle */
    pipeline: ChunkPipeline<TRecordIn, TRecordOut, CRecordIn, CRecordOut, R>
    /** Mints the cycle state — lazily for the first drained result, and again after every flush */
    initialState: () => TState | Promise<TState>
    /** Folds every drained record result into the cycle state — see {@link CycleReducer} */
    reduce: CycleReducer<TState, TRecordOut, CRecordOut, R>
    /**
     * Builds the flush pipeline run on the size or age trigger. It receives one element: the cycle
     * state.
     */
    flush: (
        builder: ChunkPipelineBuilder<TState, TState, Record<string, never>>
    ) => ChunkPipelineBuilder<TState, TFlushOut, Record<string, never>, CFlushOut, R>
    /** Size predicate: returns true when the current cycle should flush */
    shouldFlush: (state: TState) => boolean
    /** Maximum age of a cycle in milliseconds before the timer flushes it */
    maxCycleAgeMs: number
}): AccumulatingPipeline<TRecordIn, TRecordOut, CRecordIn, CRecordOut, TState, TFlushOut, CFlushOut, R> {
    const flushPipeline = config
        .flush(new ChunkPipelineBuilder(new BufferingChunkPipeline<TState, Record<string, never>>()))
        .build()
    return new AccumulatingPipeline<TRecordIn, TRecordOut, CRecordIn, CRecordOut, TState, TFlushOut, CFlushOut, R>({
        pipeline: config.pipeline,
        initialState: config.initialState,
        reduce: config.reduce,
        shouldFlush: config.shouldFlush,
        maxCycleAgeMs: config.maxCycleAgeMs,
        flushPipeline,
    })
}
