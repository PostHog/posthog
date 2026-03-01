import { BatchPipelineResultWithContext } from '../batch-pipeline.interface'
import { BatchingContext, BatchingPipeline, BatchingPipelineOptions } from '../batching-pipeline'
import { BufferingBatchPipeline } from '../buffering-batch-pipeline'
import { BatchPipelineBuilder } from './batch-pipeline-builders'
import { StartPipelineBuilder } from './pipeline-builders'

export function newBatchPipelineBuilder<T, C = Record<string, never>>(): BatchPipelineBuilder<T, T, C> {
    return new BatchPipelineBuilder(new BufferingBatchPipeline<T, C>())
}

export function newPipelineBuilder<T, C = Record<string, never>>(): StartPipelineBuilder<T, C> {
    return new StartPipelineBuilder<T, C>()
}

export function newBatchingPipeline<TInput, TOutput, CInput, CBatch, CSubOut extends BatchingContext>(
    beforeBatch: (
        elements: BatchPipelineResultWithContext<TInput, CInput & BatchingContext>,
        batchId: number
    ) => { batchContext: CBatch; elements: BatchPipelineResultWithContext<TInput, CInput & BatchingContext> },
    callback: (
        builder: BatchPipelineBuilder<TInput, TInput, CInput & BatchingContext, CInput & BatchingContext>
    ) => BatchPipelineBuilder<TInput, TOutput, CInput & BatchingContext, CSubOut>,
    afterBatch: (batchContext: CBatch, batchId: number) => void | Promise<void>,
    options?: Partial<BatchingPipelineOptions>
): BatchingPipeline<TInput, TOutput, CInput, CBatch, CInput & BatchingContext, CSubOut> {
    const startBuilder = new BatchPipelineBuilder(new BufferingBatchPipeline<TInput, CInput & BatchingContext>())
    const subPipeline = callback(startBuilder).build()
    return new BatchingPipeline(
        subPipeline,
        {
            beforeBatch,
            afterBatch: async (batchContext, results, batchId) => {
                await afterBatch(batchContext, batchId)
                return results
            },
        },
        options
    )
}
