import { Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { StepPipeline } from './step-pipeline'
import { AsyncProcessingStep, SyncProcessingStep } from './steps'

export class StartPipeline<T> implements Pipeline<T, T> {
    async process(input: PipelineResultWithContext<T>): Promise<PipelineResultWithContext<T>> {
        return Promise.resolve(input)
    }

    pipe<U>(step: SyncProcessingStep<T, U>): StepPipeline<T, T, U> {
        return new StepPipeline<T, T, U>((value) => Promise.resolve(step(value)), this)
    }

    pipeAsync<U>(step: AsyncProcessingStep<T, U>): StepPipeline<T, T, U> {
        return new StepPipeline<T, T, U>(step, this)
    }
}
