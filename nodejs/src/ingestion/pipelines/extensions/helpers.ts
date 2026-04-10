import type { PipelineResult } from '../results'
import type { ProcessingStep } from '../steps'

export function wrapStep<T, U, R extends string = never>(
    step: ProcessingStep<T, U, R>,
    wrapper: (input: T, step: ProcessingStep<T, U, R>) => Promise<PipelineResult<U, R>>
): ProcessingStep<T, U, R> {
    const wrappedStep: ProcessingStep<T, U, R> = (input) => wrapper(input, step)
    Object.defineProperty(wrappedStep, 'name', { value: step.name })
    return wrappedStep
}
