import { OkResultWithContext, Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { StepPipeline } from './step-pipeline'
import { ProcessingStep } from './steps'

export class StartPipeline<T, C> implements Pipeline<T, T, C> {
    async process(input: OkResultWithContext<T, C>): Promise<PipelineResultWithContext<T, C>> {
        return Promise.resolve(input)
    }

    pipe<U, R2 extends string = never>(step: ProcessingStep<T, U, R2>): StepPipeline<T, T, U, C, never, R2> {
        return new StepPipeline(step, this)
    }
}
