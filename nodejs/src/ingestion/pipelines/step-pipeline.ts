import { instrumentFn } from '../../common/tracing/tracing-utils'
import { pipelineStepDurationHistogram } from './metrics'
import { OkResultWithContext, Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { PipelineResult, PipelineResultType, isOkResult } from './results'
import { ProcessingStep } from './steps'

export class StepPipeline<TInput, TIntermediate, TOutput, C, RPrev extends string = never, RStep extends string = never>
    implements Pipeline<TInput, TOutput, C, RPrev | RStep>
{
    private stepName: string

    constructor(
        private currentStep: (value: TIntermediate) => Promise<PipelineResult<TOutput, RStep>>,
        private previousPipeline: Pipeline<TInput, TIntermediate, C, RPrev>
    ) {
        this.stepName = currentStep.name || 'anonymousStep'
    }

    pipe<U, R2 extends string = never>(
        step: ProcessingStep<TOutput, U, R2>
    ): StepPipeline<TInput, TOutput, U, C, RPrev | RStep, R2> {
        return new StepPipeline(step, this)
    }

    async process(
        input: OkResultWithContext<TInput, C>
    ): Promise<PipelineResultWithContext<TOutput, C, RPrev | RStep>> {
        const previousResultWithContext = await this.previousPipeline.process(input)

        const previousResult = previousResultWithContext.result
        if (!isOkResult(previousResult)) {
            return {
                result: previousResult,
                context: previousResultWithContext.context,
            }
        }

        const end = pipelineStepDurationHistogram.startTimer({ step_name: this.stepName, step_type: 'element' })
        let currentResult: PipelineResult<TOutput, RStep>
        try {
            currentResult = await instrumentFn({ key: this.stepName, sendException: false, measureTime: false }, () =>
                this.currentStep(previousResult.value)
            )
            end({ result: PipelineResultType[currentResult.type].toLowerCase() })
        } catch (e) {
            end({ result: 'exception' })
            throw e
        }
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
