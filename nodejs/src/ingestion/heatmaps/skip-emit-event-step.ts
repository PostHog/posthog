import { EmitEventStepOutput } from '../event-processing/emit-event-step'
import { PipelineResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

/**
 * Terminal step for pipelines that emit nothing themselves. Produces the same
 * output shape as the emit step (with no ingested promises) so pipelines can
 * converge on a single output type.
 */
export function createSkipEmitEventStep<TInput>(): ProcessingStep<TInput, EmitEventStepOutput> {
    return function skipEmitEventStep(_input: TInput): Promise<PipelineResult<EmitEventStepOutput>> {
        return Promise.resolve(ok({ ingested: [] }))
    }
}
