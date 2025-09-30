import { Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { StepPipeline } from './step-pipeline'
import { ProcessingStep } from './steps'

export class StartPipeline<T> implements Pipeline<T, T> {
    async process(input: PipelineResultWithContext<T>): Promise<PipelineResultWithContext<T>> {
        return Promise.resolve(input)
    }

    pipe<U>(step: ProcessingStep<T, U>): StepPipeline<T, T, U> {
        return new StepPipeline<T, T, U>(step, this)
    }
}
