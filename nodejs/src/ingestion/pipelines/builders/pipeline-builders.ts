import type { TopHogPipeOptions } from '../../tophog/tophog'
import { BranchDecisionFn, BranchingPipeline } from '../branching-pipeline'
import { Pipeline } from '../pipeline.interface'
import { RetryingPipeline, RetryingPipelineOptions } from '../retrying-pipeline'
import { StartPipeline } from '../start-pipeline'
import { StepPipeline } from '../step-pipeline'
import { ProcessingStep } from '../steps'

export class StartPipelineBuilder<T, C> {
    pipe<U>(step: ProcessingStep<T, U>, options?: { topHog?: TopHogPipeOptions<T> }): PipelineBuilder<T, U, C> {
        return new PipelineBuilder(new StepPipeline(step, new StartPipeline<T, C>(), options?.topHog))
    }

    retry<U>(
        callback: (builder: StartPipelineBuilder<T, C>) => PipelineBuilder<T, U, C>,
        options?: RetryingPipelineOptions
    ): PipelineBuilder<T, U, C> {
        const innerPipeline = callback(new StartPipelineBuilder<T, C>()).build()
        return new PipelineBuilder(new RetryingPipeline(innerPipeline, options))
    }

    branching<TBranch extends string, U>(
        decisionFn: BranchDecisionFn<T, TBranch>,
        callback: (builder: BranchingPipelineBuilder<T, T, U, C, TBranch>) => void
    ): PipelineBuilder<T, U, C> {
        const branchingBuilder = new BranchingPipelineBuilder<T, T, U, C, TBranch>(
            decisionFn,
            new StartPipeline<T, C>()
        )
        callback(branchingBuilder)
        return new PipelineBuilder(branchingBuilder.build())
    }
}

export class PipelineBuilder<TInput, TOutput, C> {
    constructor(protected pipeline: Pipeline<TInput, TOutput, C>) {}

    pipe<U>(
        step: ProcessingStep<TOutput, U>,
        options?: { topHog?: TopHogPipeOptions<TOutput> }
    ): PipelineBuilder<TInput, U, C> {
        return new PipelineBuilder(new StepPipeline(step, this.pipeline, options?.topHog))
    }

    branching<TBranch extends string, U>(
        decisionFn: BranchDecisionFn<TOutput, TBranch>,
        callback: (builder: BranchingPipelineBuilder<TInput, TOutput, U, C, TBranch>) => void
    ): PipelineBuilder<TInput, U, C> {
        const branchingBuilder = new BranchingPipelineBuilder<TInput, TOutput, U, C, TBranch>(decisionFn, this.pipeline)
        callback(branchingBuilder)
        return new PipelineBuilder(branchingBuilder.build())
    }

    build(): Pipeline<TInput, TOutput, C> {
        return this.pipeline
    }
}

export class BranchingPipelineBuilder<TInput, TIntermediate, TOutput, C, TBranch extends string> {
    private branches: Partial<Record<TBranch, Pipeline<TIntermediate, TOutput, C>>> = {}

    constructor(
        private decisionFn: BranchDecisionFn<TIntermediate, TBranch>,
        private previousPipeline: Pipeline<TInput, TIntermediate, C>
    ) {}

    branch(
        branchName: TBranch,
        callback: (builder: StartPipelineBuilder<TIntermediate, C>) => PipelineBuilder<TIntermediate, TOutput, C>
    ): BranchingPipelineBuilder<TInput, TIntermediate, TOutput, C, TBranch> {
        const branchPipeline = callback(new StartPipelineBuilder<TIntermediate, C>()).build()
        this.branches[branchName] = branchPipeline
        return this
    }

    build(): Pipeline<TInput, TOutput, C> {
        return new BranchingPipeline(
            this.decisionFn,
            this.branches as Record<TBranch, Pipeline<TIntermediate, TOutput, C>>,
            this.previousPipeline
        )
    }
}
