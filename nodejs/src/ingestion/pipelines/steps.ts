import { PipelineResult } from './results'

/**
 * Asynchronous processing step that takes a value and returns a promise of processing result
 */
export type ProcessingStep<T, U> = (value: T) => Promise<PipelineResult<U>>
