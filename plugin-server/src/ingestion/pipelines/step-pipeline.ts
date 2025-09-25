import { instrumentFn } from '../../common/tracing/tracing-utils'
import { Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { PipelineResult, isOkResult } from './results'
import { AsyncProcessingStep, SyncProcessingStep } from './steps'

export class StepPipeline<TInput, TIntermediate, TOutput> implements Pipeline<TInput, TOutput> {
    constructor(
        private currentStep: (value: TIntermediate) => Promise<PipelineResult<TOutput>>,
        private previousPipeline: Pipeline<TInput, TIntermediate>
    ) {}

    pipe<U>(step: SyncProcessingStep<TOutput, U>): StepPipeline<TInput, TOutput, U> {
        const stepName = step.name || 'anonymousStep'
        const wrappedStep = async (value: TOutput) => {
            return await instrumentFn(stepName, () => Promise.resolve(step(value)))
        }
        return new StepPipeline<TInput, TOutput, U>(wrappedStep, this)
    }

    pipeAsync<U>(step: AsyncProcessingStep<TOutput, U>): StepPipeline<TInput, TOutput, U> {
        const stepName = step.name || 'anonymousAsyncStep'
        const wrappedStep = async (value: TOutput) => {
            return await instrumentFn(stepName, () => step(value))
        }
        return new StepPipeline<TInput, TOutput, U>(wrappedStep, this)
    }

    async process(input: PipelineResultWithContext<TInput>): Promise<PipelineResultWithContext<TOutput>> {
        // Process through the previous pipeline first
        const previousResultWithContext = await this.previousPipeline.process(input)

        // If the previous step failed, return the failure with preserved context
        const previousResult = previousResultWithContext.result
        if (!isOkResult(previousResult)) {
            return {
                result: previousResult,
                context: previousResultWithContext.context,
            }
        }

        // Apply the current step to the successful result value from previous pipeline
        const currentResult = await this.currentStep(previousResult.value)

        return {
            result: currentResult,
            context: previousResultWithContext.context,
        }
    }
}
