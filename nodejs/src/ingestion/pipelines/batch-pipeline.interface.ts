import { PipelineResultWithContext } from './pipeline.interface'

/**
 * Batch processing result type
 */
export type BatchPipelineResultWithContext<T, C> = PipelineResultWithContext<T, C>[]

export type FeedResult = { ok: true } | { ok: false; reason: string }

/**
 * Interface for batch processing pipelines
 */
export interface BatchPipeline<TInput, TOutput, CInput, COutput = CInput> {
    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): FeedResult
    next(): Promise<BatchPipelineResultWithContext<TOutput, COutput> | null>
}
