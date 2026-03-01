import { BatchPipelineResultWithContext } from '../batch-pipeline.interface'
import { BatchResult, BatchingContext, BatchingPipeline, BatchingPipelineOptions } from '../batching-pipeline'
import { BufferingBatchPipeline } from '../buffering-batch-pipeline'
import { BatchPipelineBuilder } from './batch-pipeline-builders'
import { StartPipelineBuilder } from './pipeline-builders'

export function newBatchPipelineBuilder<T, C = Record<string, never>>(): BatchPipelineBuilder<T, T, C> {
    return new BatchPipelineBuilder(new BufferingBatchPipeline<T, C>())
}

export function newPipelineBuilder<T, C = Record<string, never>>(): StartPipelineBuilder<T, C> {
    return new StartPipelineBuilder<T, C>()
}

export function newBatchingPipeline<TInput, TOutput, CInput, CBatch, CSubOut>(
    beforeBatch: (
        batchContext: CBatch,
        elements: BatchPipelineResultWithContext<TInput, CInput>,
        batchId: number
    ) => BatchResult<BatchPipelineResultWithContext<TInput, CInput>>,
    callback: (
        builder: BatchPipelineBuilder<TInput, TInput, CInput & BatchingContext, CInput & BatchingContext>
    ) => BatchPipelineBuilder<TInput, TOutput, CInput & BatchingContext, CSubOut & BatchingContext>,
    afterBatch: (
        batchContext: CBatch,
        elements: BatchPipelineResultWithContext<TOutput, CSubOut & BatchingContext>,
        batchId: number
    ) => Promise<BatchResult<void>>,
    options?: Partial<BatchingPipelineOptions>
): BatchingPipeline<TInput, TOutput, CInput, CBatch, CInput & BatchingContext, CSubOut & BatchingContext> {
    const startBuilder = new BatchPipelineBuilder(new BufferingBatchPipeline<TInput, CInput & BatchingContext>())
    const subPipeline = callback(startBuilder).build()
    return new BatchingPipeline(
        subPipeline,
        {
            beforeBatch,
            afterBatch: async (batchContext, elements, batchId) => {
                const result = await afterBatch(batchContext, elements, batchId)
                return { elements, sideEffects: result.sideEffects }
            },
        },
        options
    )
}
