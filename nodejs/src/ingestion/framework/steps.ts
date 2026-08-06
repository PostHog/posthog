import { PipelineResult } from './results'

/**
 * Asynchronous processing step that takes a value and returns a pipeline result.
 *
 * @typeParam R - Union of redirect output names this step can produce.
 *   Defaults to `never` (no redirects). Steps that call `redirect()` specify
 *   the output constant (e.g. `ProcessingStep<T, U, OverflowOutput>`).
 */
export type ProcessingStep<T, U, R extends string = never> = (value: T) => Promise<PipelineResult<U, R>>
