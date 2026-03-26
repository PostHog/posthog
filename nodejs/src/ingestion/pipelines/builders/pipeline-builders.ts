import { BranchDecisionFn, BranchingPipeline } from '../branching-pipeline'
import { Pipeline } from '../pipeline.interface'
import { RetryingPipeline, RetryingPipelineOptions } from '../retrying-pipeline'
import { StartPipeline } from '../start-pipeline'
import { StepPipeline } from '../step-pipeline'
import { ProcessingStep } from '../steps'

export class StartPipelineBuilder<T, C> {
    pipe<U, R extends string = never>(step: ProcessingStep<T, U, R>): PipelineBuilder<T, U, C, R> {
        return new PipelineBuilder(new StepPipeline(step, new StartPipeline<T, C>()))
    }

    retry<U, R extends string = never>(
        callback: (builder: StartPipelineBuilder<T, C>) => PipelineBuilder<T, U, C, R>,
        options?: RetryingPipelineOptions
    ): PipelineBuilder<T, U, C, R> {
        const innerPipeline = callback(new StartPipelineBuilder<T, C>()).build()
        return new PipelineBuilder(new RetryingPipeline(innerPipeline, options))
    }

    branching<TBranch extends string, U, RBranch extends string = never>(
        decisionFn: BranchDecisionFn<T, TBranch>,
        callback: (
            builder: BranchingPipelineBuilder<T, T, U, C, TBranch>
        ) => BranchingPipelineBuilder<T, T, U, C, TBranch, never, RBranch>
    ): PipelineBuilder<T, U, C, RBranch> {
        const branchingBuilder = new BranchingPipelineBuilder<T, T, U, C, TBranch>(
            decisionFn,
            new StartPipeline<T, C>()
        )
        const finalBuilder = callback(branchingBuilder)
        return new PipelineBuilder(finalBuilder.build())
    }
}

export class PipelineBuilder<TInput, TOutput, C, R extends string = never> {
    constructor(protected pipeline: Pipeline<TInput, TOutput, C, R>) {}

    pipe<U, R2 extends string = never>(step: ProcessingStep<TOutput, U, R2>): PipelineBuilder<TInput, U, C, R | R2> {
        return new PipelineBuilder(new StepPipeline(step, this.pipeline))
    }

    branching<TBranch extends string, U, RBranch extends string = never>(
        decisionFn: BranchDecisionFn<TOutput, TBranch>,
        callback: (
            builder: BranchingPipelineBuilder<TInput, TOutput, U, C, TBranch, R>
        ) => BranchingPipelineBuilder<TInput, TOutput, U, C, TBranch, R, RBranch>
    ): PipelineBuilder<TInput, U, C, R | RBranch> {
        const branchingBuilder = new BranchingPipelineBuilder<TInput, TOutput, U, C, TBranch, R>(
            decisionFn,
            this.pipeline
        )
        const finalBuilder = callback(branchingBuilder)
        return new PipelineBuilder(finalBuilder.build())
    }

    build(): Pipeline<TInput, TOutput, C, R> {
        return this.pipeline
    }
}

export class BranchingPipelineBuilder<
    TInput,
    TIntermediate,
    TOutput,
    C,
    TBranch extends string,
    RPrev extends string = never,
    RBranch extends string = never,
> {
    constructor(
        private decisionFn: BranchDecisionFn<TIntermediate, TBranch>,
        private previousPipeline: Pipeline<TInput, TIntermediate, C, RPrev>,
        private branches: Partial<Record<TBranch, Pipeline<TIntermediate, TOutput, C, RBranch>>> = {}
    ) {}

    branch<R2 extends string = never>(
        branchName: TBranch,
        callback: (builder: StartPipelineBuilder<TIntermediate, C>) => PipelineBuilder<TIntermediate, TOutput, C, R2>
    ): BranchingPipelineBuilder<TInput, TIntermediate, TOutput, C, TBranch, RPrev, RBranch | R2> {
        const branchPipeline = callback(new StartPipelineBuilder<TIntermediate, C>()).build()
        const updatedBranches = {
            ...this.branches,
            [branchName]: branchPipeline,
        } as Partial<Record<TBranch, Pipeline<TIntermediate, TOutput, C, RBranch | R2>>>
        return new BranchingPipelineBuilder(this.decisionFn, this.previousPipeline, updatedBranches)
    }

    build(): Pipeline<TInput, TOutput, C, RPrev | RBranch> {
        return new BranchingPipeline(
            this.decisionFn,
            this.branches as Record<TBranch, Pipeline<TIntermediate, TOutput, C, RBranch>>,
            this.previousPipeline
        )
    }
}
