import { Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { StepPipeline } from './step-pipeline'
import { ProcessingStep } from './steps'

export class StartPipeline<T, C> implements Pipeline<T, T, C> {
    async process(input: PipelineResultWithContext<T, C>): Promise<PipelineResultWithContext<T, C>> {
        return Promise.resolve(input)
    }

    pipe<U>(step: ProcessingStep<T, U>): StepPipeline<T, T, U, C> {
        return new StepPipeline<T, T, U, C>(step, this)
    }
}
