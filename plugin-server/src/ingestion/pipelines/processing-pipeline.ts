import { instrumentFn } from '../../common/tracing/tracing-utils'
import {
    AsyncProcessingStep,
    ProcessingResult,
    Processor,
    ResultWithContext,
    SyncProcessingStep,
    isSuccessResult,
    success,
} from './pipeline-types'

export class NoopProcessingPipeline<T> implements Processor<T, T> {
    async process(input: ResultWithContext<T>): Promise<ResultWithContext<T>> {
        return Promise.resolve(input)
    }
}

export class ProcessingPipeline<TInput, TIntermediate, TOutput> implements Processor<TInput, TOutput> {
    constructor(
        private currentStep: (value: TIntermediate) => Promise<ProcessingResult<TOutput>>,
        private previousPipeline: Processor<TInput, TIntermediate>
    ) {}

    pipe<U>(step: SyncProcessingStep<TOutput, U>): ProcessingPipeline<TInput, TOutput, U> {
        const stepName = step.name || 'anonymousStep'
        const wrappedStep = async (value: TOutput) => {
            return await instrumentFn(stepName, () => Promise.resolve(step(value)))
        }
        return new ProcessingPipeline<TInput, TOutput, U>(wrappedStep, this)
    }

    pipeAsync<U>(step: AsyncProcessingStep<TOutput, U>): ProcessingPipeline<TInput, TOutput, U> {
        const stepName = step.name || 'anonymousAsyncStep'
        const wrappedStep = async (value: TOutput) => {
            return await instrumentFn(stepName, () => step(value))
        }
        return new ProcessingPipeline<TInput, TOutput, U>(wrappedStep, this)
    }

    async process(input: ResultWithContext<TInput>): Promise<ResultWithContext<TOutput>> {
        // Process through the previous pipeline first
        const previousResultWithContext = await this.previousPipeline.process(input)

        // If the previous step failed, return the failure with preserved context
        const previousResult = previousResultWithContext.result
        if (!isSuccessResult(previousResult)) {
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

    static create<T>(): ProcessingPipeline<T, T, T> {
        const noopStep = (value: T) => Promise.resolve(success(value))
        return new ProcessingPipeline<T, T, T>(noopStep, new NoopProcessingPipeline<T>())
    }
}
