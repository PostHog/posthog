import { Message } from 'node-rdkafka'

import { BatchPipelineUnwrapper } from './batch-pipeline-unwrapper'
import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { BufferingBatchPipeline } from './buffering-batch-pipeline'
import { Pipeline, PipelineContext, PipelineResultWithContext } from './pipeline.interface'
import { PipelineResult, ok } from './results'
import { RetryingPipeline, RetryingPipelineOptions } from './retrying-pipeline'
import { StartPipeline } from './start-pipeline'

/**
 * Helper function to create a new processing pipeline for single items
 */
export function createNewPipeline<T = { message: Message }>(): StartPipeline<T> {
    return new StartPipeline<T>()
}

/**
 * Helper function to create a new batch processing pipeline starting with a root pipeline
 */
export function createNewBatchPipeline<T = { message: Message }>(): BufferingBatchPipeline<T> {
    return new BufferingBatchPipeline<T>()
}

/**
 * Helper function to create a batch of ResultWithContext from Kafka messages or objects with a message property
 */
export function createBatch<T extends { message: Message }>(items: T[]): BatchPipelineResultWithContext<T> {
    return items.map((item) => createContext(ok(item), { message: item.message }))
}

/**
 * Helper function to create a PipelineResultWithContext from a result and partial context
 */
export function createContext<T>(
    result: PipelineResult<T>,
    partialContext: Partial<PipelineContext> & { message: Message }
): PipelineResultWithContext<T> {
    return {
        result,
        context: {
            message: partialContext.message,
            lastStep: partialContext.lastStep,
            sideEffects: partialContext.sideEffects || [],
        },
    }
}

/**
 * Helper function to create a retrying pipeline
 */
export function createRetryingPipeline<TInput, TOutput>(
    innerPipeline: Pipeline<TInput, TOutput>,
    options?: RetryingPipelineOptions
): RetryingPipeline<TInput, TOutput> {
    return new RetryingPipeline(innerPipeline, options)
}

/**
 * Helper function to create a batch pipeline unwrapper
 */
export function createUnwrapper<TInput, TOutput>(
    batchPipeline: BatchPipeline<TInput, TOutput>
): BatchPipelineUnwrapper<TInput, TOutput> {
    return new BatchPipelineUnwrapper(batchPipeline)
}
