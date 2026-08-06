import { PipelineResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

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
