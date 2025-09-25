import { PipelineResult } from './results'

/**
 * Synchronous processing step that takes a value and returns a processing result
 */
export type SyncProcessingStep<T, U> = (value: T) => PipelineResult<U>

/**
 * Asynchronous processing step that takes a value and returns a promise of processing result
 */
export type AsyncProcessingStep<T, U> = (value: T) => Promise<PipelineResult<U>>
