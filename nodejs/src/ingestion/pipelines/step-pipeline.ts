import { instrumentFn } from '../../common/tracing/tracing-utils'
import { type TopHogPipeOptions } from '../tophog/tophog'
import { Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { PipelineResult, isOkResult } from './results'
import { ProcessingStep } from './steps'

export class StepPipeline<TInput, TIntermediate, TOutput, C> implements Pipeline<TInput, TOutput, C> {
    private stepName: string

    constructor(
        private currentStep: (value: TIntermediate) => Promise<PipelineResult<TOutput>>,
        private previousPipeline: Pipeline<TInput, TIntermediate, C>,
        private topHogOptions?: TopHogPipeOptions<TIntermediate>
    ) {
        this.stepName = currentStep.name || 'anonymousStep'
    }

    pipe<U>(
        step: ProcessingStep<TOutput, U>,
        options?: { topHog?: TopHogPipeOptions<TOutput> }
    ): StepPipeline<TInput, TOutput, U, C> {
        return new StepPipeline<TInput, TOutput, U, C>(step, this, options?.topHog)
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

        const topHog = previousResultWithContext.context.topHog
        const ends =
            this.topHogOptions?.length && topHog
                ? this.topHogOptions.map((m) => m.start(topHog, previousResult.value))
                : undefined

        const currentResult = await instrumentFn({ key: this.stepName, sendException: false }, () =>
            this.currentStep(previousResult.value)
        )

        if (ends) {
            ends.forEach((end) => end())
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
