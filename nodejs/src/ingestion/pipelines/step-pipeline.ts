import { instrumentFn } from '../../common/tracing/tracing-utils'
import { Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { PipelineResult, isOkResult } from './results'
import { ProcessingStep } from './steps'

export class StepPipeline<TInput, TIntermediate, TOutput, C> implements Pipeline<TInput, TOutput, C> {
    private stepName: string

    constructor(
        private currentStep: (value: TIntermediate) => Promise<PipelineResult<TOutput>>,
        private previousPipeline: Pipeline<TInput, TIntermediate, C>
    ) {
        this.stepName = currentStep.name || 'anonymousStep'
    }

    pipe<U>(step: ProcessingStep<TOutput, U>): StepPipeline<TInput, TOutput, U, C> {
        return new StepPipeline<TInput, TOutput, U, C>(step, this)
    }

    async process(input: PipelineResultWithContext<TInput, C>): Promise<PipelineResultWithContext<TOutput, C>> {
        const previousResultWithContext = await this.previousPipeline.process(input)

        const previousResult = previousResultWithContext.result
        if (!isOkResult(previousResult)) {
            return {
                result: previousResult,
                context: previousResultWithContext.context,
            }
        }

        const currentResult = await instrumentFn({ key: this.stepName, sendException: false }, () =>
            this.currentStep(previousResult.value)
        )
        return {
            result: currentResult,
            context: {
                ...previousResultWithContext.context,
                lastStep: this.stepName,
                sideEffects: [...previousResultWithContext.context.sideEffects, ...currentResult.sideEffects],
                warnings: [...previousResultWithContext.context.warnings, ...currentResult.warnings],
            },
        }
    }
}
