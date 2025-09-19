import { instrumentFn } from '../common/tracing/tracing-utils'
import { isSuccessResult, success } from '../worker/ingestion/event-pipeline/pipeline-step-result'
import { AsyncProcessingStep, ProcessingResult, SyncProcessingStep } from './pipeline-types'

interface Processor<TInput, TIntermediate> {
    process(element: TInput): Promise<ProcessingResult<TIntermediate>>
}

export class NoopProcessingPipeline<T> implements Processor<T, T> {
    async process(element: T): Promise<ProcessingResult<T>> {
        return Promise.resolve(success(element))
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

    async process(element: TInput): Promise<ProcessingResult<TOutput>> {
        // Process through the previous pipeline first (with the same input)
        const previousResult = await this.previousPipeline.process(element)

        // If the previous step failed, return the failure
        if (!isSuccessResult(previousResult)) {
            return previousResult
        }

        // Apply the current step to the successful result value from previous pipeline
        return await this.currentStep(previousResult.value)
    }

    static create<T>(): ProcessingPipeline<T, T, T> {
        const noopStep = (value: T) => Promise.resolve(success(value))
        return new ProcessingPipeline<T, T, T>(noopStep, new NoopProcessingPipeline<T>())
    }
}
