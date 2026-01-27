import { PipelineResultWithContext } from './pipeline.interface'

/**
 * Batch processing result type
 */
export type BatchPipelineResultWithContext<T, C> = PipelineResultWithContext<T, C>[]

/**
 * Interface for batch processing pipelines
 */
export interface BatchPipeline<TInput, TOutput, CInput, COutput = CInput> {
    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): void
    next(): Promise<BatchPipelineResultWithContext<TOutput, COutput> | null>
}
