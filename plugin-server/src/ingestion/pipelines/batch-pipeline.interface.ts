import { PipelineResultWithContext } from './pipeline.interface'

/**
 * Batch processing result type
 */
export type BatchPipelineResultWithContext<T> = PipelineResultWithContext<T>[]

/**
 * Interface for batch processing pipelines
 */
export interface BatchPipeline<TInput, TIntermediate> {
    feed(elements: BatchPipelineResultWithContext<TInput>): void
    next(): Promise<BatchPipelineResultWithContext<TIntermediate> | null>
}
