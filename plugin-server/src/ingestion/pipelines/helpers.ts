import { Message } from 'node-rdkafka'

import { BatchPipelineUnwrapper } from './batch-pipeline-unwrapper'
import { BatchPipeline } from './batch-pipeline.interface'
import { BatchPipelineBuilder, newBatchPipelineBuilder } from './builders'
import { PipelineWarning } from './pipeline.interface'
import { PipelineResult, ok } from './results'
import { StartPipeline } from './start-pipeline'

export type DefaultContext = { message: Message }

/**
 * Minimal team type for team-aware pipelines that only need the team ID
 */
export type PipelineTeam = { id: number }

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
 * Result type for createContext that represents the actual shape of the returned context
 */
export type CreateContextResult<T, PartialContext> = {
    result: PipelineResult<T>
    context: {
        message: Message
        lastStep: string | undefined
        sideEffects: Promise<unknown>[]
        warnings: PipelineWarning[]
    } & Omit<PartialContext, 'message' | 'lastStep' | 'sideEffects' | 'warnings'>
}

/**
 * Helper function to create a PipelineResultWithContext from a result and partial context
 */
export function createContext<T, PartialContext>(
    result: PipelineResult<T>,
    partialContext: PartialContext & {
        message: Message
        lastStep?: string
        sideEffects?: Promise<unknown>[]
        warnings?: PipelineWarning[]
    }
): CreateContextResult<T, PartialContext> {
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
 * Helper function to create a batch pipeline unwrapper
 */
export function createUnwrapper<TInput, TOutput, C>(
    batchPipeline: BatchPipeline<TInput, TOutput, C>
): BatchPipelineUnwrapper<TInput, TOutput, C> {
    return new BatchPipelineUnwrapper(batchPipeline)
}
