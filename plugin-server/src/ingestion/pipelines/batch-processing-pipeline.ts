import { instrumentFn } from '../../common/tracing/tracing-utils'
import {
    BatchProcessingPipeline,
    BatchProcessingResult,
    PipelineStepResult,
    PipelineStepResultOk,
    ResultWithContext,
    isSuccessResult,
} from './pipeline-types'

/**
 * Type guard for ResultWithContext that asserts the result is successful
 */
function isSuccessResultWithContext<T>(
    resultWithContext: ResultWithContext<T>
): resultWithContext is ResultWithContext<T> & { result: PipelineStepResultOk<T> } {
    return isSuccessResult(resultWithContext.result)
}

export type BatchProcessingStep<T, U> = (values: T[]) => Promise<PipelineStepResult<U>[]>

export class SequentialBatchProcessingPipeline<TInput, TIntermediate, TOutput>
    implements BatchProcessingPipeline<TInput, TOutput>
{
    constructor(
        private currentStep: BatchProcessingStep<TIntermediate, TOutput>,
        private previousPipeline: BatchProcessingPipeline<TInput, TIntermediate>
    ) {}

    feed(elements: BatchProcessingResult<TInput>): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchProcessingResult<TOutput> | null> {
        const previousResults = await this.previousPipeline.next()
        if (previousResults === null) {
            return null
        }

        // Filter successful values for processing
        const successfulValues = previousResults
            .filter(isSuccessResultWithContext)
            .map((resultWithContext) => resultWithContext.result.value)

        // Apply current step to successful values
        const stepName = this.currentStep.name || 'anonymousBatchStep'
        let stepResults: PipelineStepResult<TOutput>[] = []
        if (successfulValues.length > 0) {
            stepResults = await instrumentFn(stepName, () => this.currentStep(successfulValues))
        }
        let stepIndex = 0

        // Map results back, preserving context and non-successful results
        return previousResults.map((resultWithContext) => {
            if (isSuccessResult(resultWithContext.result)) {
                return {
                    result: stepResults[stepIndex++],
                    context: resultWithContext.context,
                }
            } else {
                return {
                    result: resultWithContext.result,
                    context: resultWithContext.context,
                }
            }
        })
    }

    static from<TInput, TIntermediate, TOutput>(
        step: BatchProcessingStep<TIntermediate, TOutput>,
        subPipeline: BatchProcessingPipeline<TInput, TIntermediate>
    ): SequentialBatchProcessingPipeline<TInput, TIntermediate, TOutput> {
        const pipeline = subPipeline
        return new SequentialBatchProcessingPipeline<TInput, TIntermediate, TOutput>(step, pipeline)
    }
}
