import { instrumentFn } from '../../common/tracing/tracing-utils'
import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { PipelineResultWithContext } from './pipeline.interface'
import { PipelineResult, PipelineResultOk, isOkResult } from './results'

/**
 * Type guard for ResultWithContext that asserts the result is successful
 */
function isSuccessResultWithContext<T>(
    resultWithContext: PipelineResultWithContext<T>
): resultWithContext is PipelineResultWithContext<T> & { result: PipelineResultOk<T> } {
    return isOkResult(resultWithContext.result)
}

export type BatchProcessingStep<T, U> = (values: T[]) => Promise<PipelineResult<U>[]>

export class BaseBatchPipeline<TInput, TIntermediate, TOutput> implements BatchPipeline<TInput, TOutput> {
    private stepName: string

    constructor(
        private currentStep: BatchProcessingStep<TIntermediate, TOutput>,
        private previousPipeline: BatchPipeline<TInput, TIntermediate>
    ) {
        this.stepName = this.currentStep.name || 'anonymousBatchStep'
    }

    feed(elements: BatchPipelineResultWithContext<TInput>): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput> | null> {
        const previousResults = await this.previousPipeline.next()
        if (previousResults === null) {
            return null
        }

        // Filter successful values for processing
        const successfulValues = previousResults
            .filter(isSuccessResultWithContext)
            .map((resultWithContext) => resultWithContext.result.value)

        // Apply current step to successful values
        let stepResults: PipelineResult<TOutput>[] = []
        if (successfulValues.length > 0) {
            stepResults = await instrumentFn({ key: this.stepName, sendException: false }, () =>
                this.currentStep(successfulValues)
            )
        }
        let stepIndex = 0

        // Map results back, preserving context and non-successful results
        return previousResults.map((resultWithContext) => {
            if (isOkResult(resultWithContext.result)) {
                return {
                    result: stepResults[stepIndex++],
                    context: {
                        ...resultWithContext.context,
                        lastStep: this.stepName,
                    },
                }
            } else {
                return {
                    result: resultWithContext.result,
                    context: resultWithContext.context,
                }
            }
        })
    }
}
