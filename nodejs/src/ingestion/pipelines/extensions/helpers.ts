import type { PipelineResult } from '../results'
import type { ProcessingStep } from '../steps'

export function wrapStep<T, U>(
    step: ProcessingStep<T, U>,
    wrapper: (input: T, step: ProcessingStep<T, U>) => Promise<PipelineResult<U>>
): ProcessingStep<T, U> {
    const wrappedStep: ProcessingStep<T, U> = (input) => wrapper(input, step)
    Object.defineProperty(wrappedStep, 'name', { value: step.name })
    return wrappedStep
}
