import type { BatchProcessingStep } from '../base-batch-pipeline'
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

export function wrapBatchStep<T, U>(
    step: BatchProcessingStep<T, U>,
    wrapper: (inputs: T[], step: BatchProcessingStep<T, U>) => Promise<PipelineResult<U>[]>
): BatchProcessingStep<T, U> {
    const wrappedStep: BatchProcessingStep<T, U> = (inputs) => wrapper(inputs, step)
    Object.defineProperty(wrappedStep, 'name', { value: step.name || 'anonymousBatchStep' })
    return wrappedStep
}
