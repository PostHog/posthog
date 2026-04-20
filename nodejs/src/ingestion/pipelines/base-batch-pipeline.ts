import { instrumentFn } from '../../common/tracing/tracing-utils'
import { BatchPipeline, BatchPipelineResultWithContext, OkResultWithContext } from './batch-pipeline.interface'
import { pipelineStepDurationHistogram } from './metrics'
import { PipelineResultWithContext } from './pipeline.interface'
import { PipelineResult, PipelineResultOk, isOkResult } from './results'

/**
 * Type guard for ResultWithContext that asserts the result is successful
 */
function isSuccessResultWithContext<T, C, R extends string>(
    resultWithContext: PipelineResultWithContext<T, C, R>
): resultWithContext is PipelineResultWithContext<T, C, R> & { result: PipelineResultOk<T> } {
    return isOkResult(resultWithContext.result)
}

/**
 * Batch processing step that takes an array of values and returns a result per value.
 *
 * @typeParam R - Union of redirect output names this step can produce.
 *   Defaults to `never` (no redirects).
 */
export type BatchProcessingStep<T, U, R extends string = never> = (values: T[]) => Promise<PipelineResult<U, R>[]>

export class BaseBatchPipeline<
    TInput,
    TIntermediate,
    TOutput,
    CInput,
    COutput = CInput,
    RPrev extends string = never,
    RStep extends string = never,
> implements BatchPipeline<TInput, TOutput, CInput, COutput, RPrev | RStep>
{
    private stepName: string

    constructor(
        private currentStep: BatchProcessingStep<TIntermediate, TOutput, RStep>,
        private previousPipeline: BatchPipeline<TInput, TIntermediate, CInput, COutput, RPrev>
    ) {
        this.stepName = this.currentStep.name || 'anonymousBatchStep'
    }

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput, RPrev | RStep> | null> {
        const previousResults = await this.previousPipeline.next()
        if (previousResults === null) {
            return null
        }

        // Filter successful values for processing
        const successfulValues = previousResults
            .filter(isSuccessResultWithContext)
            .map((resultWithContext) => resultWithContext.result.value)

        // Apply current step to successful values
        let stepResults: PipelineResult<TOutput, RStep>[] = []
        if (successfulValues.length > 0) {
            const end = pipelineStepDurationHistogram.startTimer({ step_name: this.stepName, step_type: 'batch' })
            try {
                stepResults = await instrumentFn({ key: this.stepName, sendException: false, measureTime: false }, () =>
                    this.currentStep(successfulValues)
                )
                end({ result: 'batch' })
            } catch (e) {
                end({ result: 'exception' })
                throw e
            }
            if (stepResults.length !== successfulValues.length) {
                throw new Error(
                    `Batch pipeline step ${this.stepName} returned different number of results than input values: ${stepResults.length} !== ${successfulValues.length}`
                )
            }
        }
        let stepIndex = 0

        // Map results back, preserving context and non-successful results
        const output: BatchPipelineResultWithContext<TOutput, COutput, RPrev | RStep> = []
        for (const resultWithContext of previousResults) {
            if (isOkResult(resultWithContext.result)) {
                const stepResult = stepResults[stepIndex++]
                output.push({
                    result: stepResult,
                    context: {
                        ...resultWithContext.context,
                        lastStep: this.stepName,
                        sideEffects: [...resultWithContext.context.sideEffects, ...stepResult.sideEffects],
                        warnings: [...resultWithContext.context.warnings, ...stepResult.warnings],
                    },
                })
            } else {
                output.push({
                    result: resultWithContext.result,
                    context: resultWithContext.context,
                })
            }
        }
        return output
    }
}
