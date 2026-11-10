import { PipelineResult, ok } from '@posthog/ingestion-common/framework/results'
import { ProcessingStep } from '@posthog/ingestion-common/framework/steps'

export function createDisablePersonProcessingStep<TInput>(): ProcessingStep<
    TInput,
    TInput & { processPerson: boolean }
> {
    return async function disablePersonProcessingStep(
        input: TInput
    ): Promise<PipelineResult<TInput & { processPerson: boolean }>> {
        return Promise.resolve(
            ok({
                ...input,
                processPerson: false,
            })
        )
    }
}
