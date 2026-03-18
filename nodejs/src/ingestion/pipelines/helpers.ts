import { Message } from 'node-rdkafka'

import { BatchPipelineUnwrapper } from './batch-pipeline-unwrapper'
import { BatchPipeline } from './batch-pipeline.interface'
import { BatchPipelineBuilder, newBatchPipelineBuilder } from './builders'
import { PipelineWarning } from './pipeline.interface'
import { PipelineResult, ok } from './results'
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
export function createNewBatchPipeline<T = { message: Message }, C = DefaultContext>(): BatchPipelineBuilder<T, T, C> {
    return newBatchPipelineBuilder<T, C>()
}

/**
 * Helper function to create a batch of ResultWithContext from Kafka messages or objects with a message property
 */
export function createBatch<T extends DefaultContext>(items: T[]) {
    return items.map((item) => createContext(ok(item), { message: item.message }))
}

/**
 * Base context properties that are always present in pipeline context
 */
export type BasePipelineContext = {
    lastStep?: string
    sideEffects?: Promise<unknown>[]
    warnings?: PipelineWarning[]
}

/**
 * Result type for createContext that represents the actual shape of the returned context
 */
export type CreateContextResult<T, PartialContext> = {
    result: PipelineResult<T>
    context: {
        lastStep: string | undefined
        sideEffects: Promise<unknown>[]
        warnings: PipelineWarning[]
    } & PartialContext
}

/**
 * Helper function to create a PipelineResultWithContext from a result and partial context
 */
export function createContext<T, PartialContext extends Record<string, unknown> = Record<string, never>>(
    result: PipelineResult<T>,
    ...args: PartialContext extends Record<string, never>
        ? [partialContext?: PartialContext & BasePipelineContext]
        : [partialContext: PartialContext & BasePipelineContext]
): CreateContextResult<T, PartialContext> {
    const partialContext = args[0] || ({} as PartialContext & BasePipelineContext)
    const { lastStep, sideEffects, warnings, ...rest } = partialContext
    return {
        result,
        context: {
            lastStep: lastStep,
            sideEffects: sideEffects || [],
            warnings: warnings || [],
            ...rest,
        } as CreateContextResult<T, PartialContext>['context'],
    }
}

/**
 * Helper function to create a batch pipeline unwrapper
 */
export function createUnwrapper<TInput, TOutput, C>(
    batchPipeline: BatchPipeline<TInput, TOutput, C>
): BatchPipelineUnwrapper<TInput, TOutput, C> {
    return new BatchPipelineUnwrapper(batchPipeline)
}
