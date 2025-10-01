import { instrumentFn } from '../../common/tracing/tracing-utils'
import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { PipelineResultWithContext } from './pipeline.interface'
import { PipelineResult, PipelineResultOk, isOkResult } from './results'

/**
 * Type guard for ResultWithContext that asserts the result is successful
 */
function isSuccessResultWithContext<T, C>(
    resultWithContext: PipelineResultWithContext<T, C>
): resultWithContext is PipelineResultWithContext<T, C> & { result: PipelineResultOk<T> } {
    return isOkResult(resultWithContext.result)
}

export type BatchProcessingStep<T, U> = (values: T[]) => Promise<PipelineResult<U>[]>

export class BaseBatchPipeline<TInput, TIntermediate, TOutput, C> implements BatchPipeline<TInput, TOutput, C> {
    private stepName: string

    constructor(
        private currentStep: BatchProcessingStep<TIntermediate, TOutput>,
        private previousPipeline: BatchPipeline<TInput, TIntermediate, C>
    ) {
        this.stepName = this.currentStep.name || 'anonymousBatchStep'
    }

    feed(elements: BatchPipelineResultWithContext<TInput, C>): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, C> | null> {
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
            if (stepResults.length !== successfulValues.length) {
                throw new Error(
                    `Batch pipeline step ${this.stepName} returned different number of results than input values: ${stepResults.length} !== ${successfulValues.length}`
                )
            }
        }
        let stepIndex = 0

        // Map results back, preserving context and non-successful results
        return previousResults.map((resultWithContext) => {
            if (isOkResult(resultWithContext.result)) {
                const stepResult = stepResults[stepIndex++]
                return {
                    result: stepResult,
                    context: {
                        ...resultWithContext.context,
                        lastStep: this.stepName,
                        sideEffects: [...resultWithContext.context.sideEffects, ...stepResult.sideEffects],
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
