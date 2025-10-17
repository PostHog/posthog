import { Message } from 'node-rdkafka'

import { PipelineResult } from './results'

export interface PipelineWarning {
    type: string
    details: Record<string, any>
    alwaysSend?: boolean
}

/**
 * Processing context that carries message through pipeline transformations
 */
export type PipelineContext<C = { message: Message }> = C & {
    lastStep?: string
    sideEffects: Promise<unknown>[]
    warnings: PipelineWarning[]
}

/**
 * Result with context wrapper that carries both the pipeline result and processing context
 */
export interface PipelineResultWithContext<T, C = { message: Message }> {
    result: PipelineResult<T>
    context: PipelineContext<C>
}

/**
 * Interface for single-item processors
 */
export interface Pipeline<TInput, TOutput, C = { message: Message }> {
    process(input: PipelineResultWithContext<TInput, C>): Promise<PipelineResultWithContext<TOutput, C>>
}
