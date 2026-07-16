import type { OkResultWithContext, PipelineResultWithContext } from './pipeline.interface'

export type { OkResultWithContext }

/**
 * Result type for a chunk of processed elements.
 *
 * A chunk is the array of elements a stage processes and passes on; it can hold
 * elements from multiple batches (a batch = one `feed()` call).
 * `R` is the union of redirect output names results can carry.
 */
export type ChunkPipelineResultWithContext<T, C, R extends string = never> = PipelineResultWithContext<T, C, R>[]

/**
 * Interface for chunk-processing pipeline stages.
 *
 * `feed()` accepts one batch of OK results; `next()` pulls the processed chunk,
 * which may combine elements from several fed batches. Non-OK results (DLQ,
 * DROP, REDIRECT) are produced by pipeline steps, not fed from outside.
 * `R` is the union of redirect output names that can flow through this pipeline.
 */
export interface ChunkPipeline<TInput, TOutput, CInput, COutput = CInput, R extends string = never> {
    feed(elements: OkResultWithContext<TInput, CInput>[]): void
    next(): Promise<ChunkPipelineResultWithContext<TOutput, COutput, R> | null>
}
