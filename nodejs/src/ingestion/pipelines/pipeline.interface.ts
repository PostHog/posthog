import { Message } from 'node-rdkafka'

import { PipelineResult, PipelineResultOk } from './results'

export interface PipelineWarning {
    type: string
    details: Record<string, any>
    key?: string
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
 * Result with context wrapper that carries both the pipeline result and processing context.
 *
 * `R` is the union of redirect output names this result can carry.
 */
export interface PipelineResultWithContext<T, C = { message: Message }, R extends string = never> {
    result: PipelineResult<T, R>
    context: PipelineContext<C>
}

/** An OK result with context — the only type that can be fed into a pipeline. */
export interface OkResultWithContext<T, C = { message: Message }> {
    result: PipelineResultOk<T>
    context: PipelineContext<C>
}

/**
 * Interface for single-item processors.
 *
 * @typeParam R - Union of redirect output names that can flow through this pipeline.
 *   Defaults to `never` (no redirects). Widens as steps that redirect are composed in.
 */
export interface Pipeline<TInput, TOutput, C = { message: Message }, R extends string = never> {
    process(input: OkResultWithContext<TInput, C>): Promise<PipelineResultWithContext<TOutput, C, R>>
}
