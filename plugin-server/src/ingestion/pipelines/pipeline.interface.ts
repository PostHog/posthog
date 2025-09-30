import { Message } from 'node-rdkafka'

import { PipelineResult } from './results'

/**
 * Processing context that carries message through pipeline transformations
 */
export interface PipelineContext {
    message: Message
    lastStep?: string
}

/**
 * Result with context wrapper that carries both the pipeline result and processing context
 */
export interface PipelineResultWithContext<T> {
    result: PipelineResult<T>
    context: PipelineContext
}

/**
 * Interface for single-item processors
 */
export interface Pipeline<TInput, TOutput> {
    process(input: PipelineResultWithContext<TInput>): Promise<PipelineResultWithContext<TOutput>>
}
