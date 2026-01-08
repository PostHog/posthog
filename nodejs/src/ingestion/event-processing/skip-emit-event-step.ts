import { PipelineResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export function createSkipEmitEventStep<TInput>(): ProcessingStep<TInput, void> {
    return function skipEmitEventStep(_input: TInput): Promise<PipelineResult<void>> {
        return Promise.resolve(ok(undefined))
    }
}
