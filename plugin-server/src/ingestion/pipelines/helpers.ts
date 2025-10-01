import { Message } from 'node-rdkafka'

import { BatchPipelineUnwrapper } from './batch-pipeline-unwrapper'
import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { BufferingBatchPipeline } from './buffering-batch-pipeline'
import { Pipeline, PipelineContext, PipelineResultWithContext } from './pipeline.interface'
import { PipelineResult, ok } from './results'
import { RetryingPipeline, RetryingPipelineOptions } from './retrying-pipeline'
import { StartPipeline } from './start-pipeline'

export type DefaultContext = { message: Message }

/**
 * Helper function to create a new processing pipeline for single items
 */
export function createNewPipeline<T = { message: Message }, C = DefaultContext>(): StartPipeline<T, C> {
    return new StartPipeline<T, C>()
}

/**
 * Helper function to create a new batch processing pipeline starting with a root pipeline
 */
export function createNewBatchPipeline<T, C = DefaultContext>(): BufferingBatchPipeline<T, C> {
    return new BufferingBatchPipeline<T, C>()
}

/**
 * Helper function to create a batch of ResultWithContext from Kafka messages or objects with a message property
 */
export function createBatch<T extends DefaultContext>(items: T[]): BatchPipelineResultWithContext<T, DefaultContext> {
    return items.map((item) => createContext(ok(item), { message: item.message }))
}

/**
 * Helper function to create a PipelineResultWithContext from a result and partial context
 */
export function createContext<T, C>(
    result: PipelineResult<T>,
    partialContext: Partial<PipelineContext<C>> & DefaultContext
): PipelineResultWithContext<T> {
    const { message, lastStep, sideEffects, warnings, ...rest } = partialContext
    return {
        result,
        context: {
            message: message,
            lastStep: lastStep,
            sideEffects: sideEffects || [],
            warnings: warnings || [],
            ...rest,
        },
    }
}

/**
 * Helper function to create a retrying pipeline
 */
export function createRetryingPipeline<TInput, TOutput, C>(
    innerPipeline: Pipeline<TInput, TOutput, C>,
    options?: RetryingPipelineOptions
): RetryingPipeline<TInput, TOutput, C> {
    return new RetryingPipeline(innerPipeline, options)
}

/**
 * Helper function to create a batch pipeline unwrapper
 */
export function createUnwrapper<TInput, TOutput, C>(
    batchPipeline: BatchPipeline<TInput, TOutput, C>
): BatchPipelineUnwrapper<TInput, TOutput, C> {
    return new BatchPipelineUnwrapper(batchPipeline)
}
