import { instrumentFn } from '~/common/tracing/tracing-utils'

import { AsyncProcessingStep, Pipeline, PipelineResultWithContext, SyncProcessingStep } from './pipeline-types'
import { StepPipeline } from './step-pipeline'

export class StartPipeline<T> implements Pipeline<T, T> {
    async process(input: PipelineResultWithContext<T>): Promise<PipelineResultWithContext<T>> {
        return Promise.resolve(input)
    }

    pipe<U>(step: SyncProcessingStep<T, U>): StepPipeline<T, T, U> {
        const stepName = step.name || 'anonymousStep'
        const wrappedStep = async (value: T) => {
            return await instrumentFn(stepName, () => Promise.resolve(step(value)))
        }
        return new StepPipeline<T, T, U>(wrappedStep, this)
    }

    pipeAsync<U>(step: AsyncProcessingStep<T, U>): StepPipeline<T, T, U> {
        const stepName = step.name || 'anonymousAsyncStep'
        const wrappedStep = async (value: T) => {
            return await instrumentFn(stepName, () => step(value))
        }
        return new StepPipeline<T, T, U>(wrappedStep, this)
    }
}
