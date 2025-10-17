import { Pipeline } from '../pipeline.interface'
import { RetryingPipeline, RetryingPipelineOptions } from '../retrying-pipeline'
import { StartPipeline } from '../start-pipeline'
import { StepPipeline } from '../step-pipeline'
import { ProcessingStep } from '../steps'

export class StartPipelineBuilder<T, C> {
    pipe<U>(step: ProcessingStep<T, U>): PipelineBuilder<T, U, C> {
        return new PipelineBuilder(new StepPipeline(step, new StartPipeline<T, C>()))
    }

    retry<U>(
        callback: (builder: StartPipelineBuilder<T, C>) => PipelineBuilder<T, U, C>,
        options?: RetryingPipelineOptions
    ): PipelineBuilder<T, U, C> {
        const innerPipeline = callback(new StartPipelineBuilder<T, C>()).build()
        return new PipelineBuilder(new RetryingPipeline(innerPipeline, options))
    }
}

export class PipelineBuilder<TInput, TOutput, C> {
    constructor(protected pipeline: Pipeline<TInput, TOutput, C>) {}

    pipe<U>(step: ProcessingStep<TOutput, U>): PipelineBuilder<TInput, U, C> {
        return new PipelineBuilder(new StepPipeline(step, this.pipeline))
    }

    build(): Pipeline<TInput, TOutput, C> {
        return this.pipeline
    }
}
