import { OkResultWithContext, PipelineResultWithContext } from './pipeline.interface'

export { OkResultWithContext }

/**
 * Batch processing result type.
 *
 * `R` is the union of redirect output names results can carry.
 */
export type BatchPipelineResultWithContext<T, C, R extends string = never> = PipelineResultWithContext<T, C, R>[]

/**
 * Interface for batch processing pipelines.
 *
 * `R` is the union of redirect output names that can flow through this pipeline.
 * `feed()` only accepts OK results — non-OK results (DLQ, DROP, REDIRECT) are
 * produced by pipeline steps, not fed from outside.
 */
export interface BatchPipeline<TInput, TOutput, CInput, COutput = CInput, R extends string = never> {
    feed(elements: OkResultWithContext<TInput, CInput>[]): void
    next(): Promise<BatchPipelineResultWithContext<TOutput, COutput, R> | null>
}
