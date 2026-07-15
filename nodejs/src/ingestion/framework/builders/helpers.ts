import {
    AccumulatingPipeline,
    BeforeCycleInput,
    BeforeCycleOutput,
    CycleContext,
    CycleFlushInput,
} from '~/ingestion/framework/accumulating-pipeline'
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
 * Builder-style constructor for AccumulatingPipeline, mirroring newBatchingPipeline: `beforeCycle`
 * and `flush` are builder callbacks that get `.build()`-ed for you. The record `pipeline` is passed
 * pre-built, since deployments choose it (e.g. the default vs ML-mirror session replay pipeline).
 */
export function newAccumulatingPipeline<
    TRecordIn extends object, // element fed in per message (cycle context is added internally)
    TRecordOut, // element out of the per-message pipeline; accumulates as a bare result
    CRecordIn, // per-message pipeline context in
    CRecordOut, // per-message pipeline context out (dropped when results accumulate)
    CCycle, // cycle context minted per cycle, tagged on every element and the flush unit
    TFlushOut, // element out of the flush pipeline
    CFlushOut = Record<string, never>, // flush-pipeline context out
    R extends string = never, // redirect output names this pipeline can emit
>(config: {
    /** Builds the beforeCycle pipeline that mints a fresh cycle context (e.g. the recorder) each cycle */
    beforeCycle: (
        builder: StartPipelineBuilder<BeforeCycleInput, Record<string, never>>
    ) => PipelineBuilder<BeforeCycleInput, BeforeCycleOutput<CCycle>, Record<string, never>>
    /** Pre-built record pipeline (a plain chunk pipeline) that folds each message into the current cycle context */
    pipeline: ChunkPipeline<TRecordIn & CCycle & CycleContext, TRecordOut, CRecordIn, CRecordOut, R>
    /**
     * Builds the flush pipeline run on the size or age trigger. It receives one
     * {@link CycleFlushInput}: the cycle context plus every accumulated record result in drain
     * order.
     */
    flush: (
        builder: ChunkPipelineBuilder<
            CycleFlushInput<TRecordOut, CCycle, R>,
            CycleFlushInput<TRecordOut, CCycle, R>,
            Record<string, never>
        >
    ) => ChunkPipelineBuilder<CycleFlushInput<TRecordOut, CCycle, R>, TFlushOut, Record<string, never>, CFlushOut, R>
    /** Size predicate: returns true when the current cycle should flush */
    shouldFlush: (cycleContext: CCycle & CycleContext) => boolean
    /** Maximum age of a cycle in milliseconds before the timer flushes it */
    maxCycleAgeMs: number
}): AccumulatingPipeline<TRecordIn, TRecordOut, CRecordIn, CRecordOut, CCycle, TFlushOut, CFlushOut, R> {
    const beforeCycle = config.beforeCycle(new StartPipelineBuilder<BeforeCycleInput, Record<string, never>>()).build()
    const flushPipeline = config
        .flush(
            new ChunkPipelineBuilder(
                new BufferingChunkPipeline<CycleFlushInput<TRecordOut, CCycle, R>, Record<string, never>>()
            )
        )
        .build()
    return new AccumulatingPipeline<TRecordIn, TRecordOut, CRecordIn, CRecordOut, CCycle, TFlushOut, CFlushOut, R>({
        beforeCycle,
        pipeline: config.pipeline,
        shouldFlush: config.shouldFlush,
        maxCycleAgeMs: config.maxCycleAgeMs,
        flushPipeline,
    })
}
