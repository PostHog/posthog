import { BranchDecisionFn, BranchingPipeline } from '~/ingestion/framework/branching-pipeline'
import { Pipeline } from '~/ingestion/framework/pipeline.interface'
import { RetryOptions, withStepRetry } from '~/ingestion/framework/retry'
import { StartPipeline } from '~/ingestion/framework/start-pipeline'
import { StepPipeline } from '~/ingestion/framework/step-pipeline'
import { ProcessingStep } from '~/ingestion/framework/steps'

export class StartPipelineBuilder<T, C> {
    pipe<U, R extends string = never>(
        step: ProcessingStep<T, U, R>,
        options?: { retry?: RetryOptions }
    ): PipelineBuilder<T, U, C, R> {
        const wrappedStep = options?.retry ? withStepRetry(step, options.retry) : step
        return new PipelineBuilder(new StepPipeline(wrappedStep, new StartPipeline<T, C>()))
    }

    branching<TBranch extends string, U, RBranch extends string = never>(
        decisionFn: BranchDecisionFn<T, TBranch>,
        callback: (
            builder: BranchingPipelineBuilder<T, T, U, C, TBranch, TBranch>
        ) => BranchingPipelineBuilder<T, T, U, C, TBranch, never, never, RBranch>
    ): PipelineBuilder<T, U, C, RBranch> {
        const branchingBuilder = new BranchingPipelineBuilder<T, T, U, C, TBranch, TBranch>(
            decisionFn,
            new StartPipeline<T, C>()
        )
        const finalBuilder = callback(branchingBuilder)
        return new PipelineBuilder(finalBuilder.build())
    }
}

export class PipelineBuilder<TInput, TOutput, C, R extends string = never> {
    constructor(protected pipeline: Pipeline<TInput, TOutput, C, R>) {}

    pipe<U, R2 extends string = never>(
        step: ProcessingStep<TOutput, U, R2>,
        options?: { retry?: RetryOptions }
    ): PipelineBuilder<TInput, U, C, R | R2> {
        const wrappedStep = options?.retry ? withStepRetry(step, options.retry) : step
        return new PipelineBuilder(new StepPipeline(wrappedStep, this.pipeline))
    }

    branching<TBranch extends string, U, RBranch extends string = never>(
        decisionFn: BranchDecisionFn<TOutput, TBranch>,
        callback: (
            builder: BranchingPipelineBuilder<TInput, TOutput, U, C, TBranch, TBranch, R>
        ) => BranchingPipelineBuilder<TInput, TOutput, U, C, TBranch, never, R, RBranch>
    ): PipelineBuilder<TInput, U, C, R | RBranch> {
        const branchingBuilder = new BranchingPipelineBuilder<TInput, TOutput, U, C, TBranch, TBranch, R>(
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

/**
 * Builder for branching pipelines that tracks remaining branches via TRemaining.
 *
 * Each branch() call removes a branch from TRemaining via Exclude.
 * build() requires TRemaining = never, ensuring all branches are supplied at compile time.
 */
export class BranchingPipelineBuilder<
    TInput,
    TIntermediate,
    TOutput,
    C,
    TBranch extends string,
    TRemaining extends TBranch = TBranch,
    RPrev extends string = never,
    RBranch extends string = never,
> {
    constructor(
        private decisionFn: BranchDecisionFn<TIntermediate, TBranch>,
        private previousPipeline: Pipeline<TInput, TIntermediate, C, RPrev>,
        private branches: Partial<Record<TBranch, Pipeline<TIntermediate, TOutput, C, RBranch>>> = {}
    ) {}

    branch<B extends TRemaining, R2 extends string = never>(
        branchName: B,
        callback: (builder: StartPipelineBuilder<TIntermediate, C>) => PipelineBuilder<TIntermediate, TOutput, C, R2>
    ): BranchingPipelineBuilder<
        TInput,
        TIntermediate,
        TOutput,
        C,
        TBranch,
        Exclude<TRemaining, B>,
        RPrev,
        RBranch | R2
    > {
        const branchPipeline = callback(new StartPipelineBuilder<TIntermediate, C>()).build()
        // Split spread and computed key into two statements — the spread preserves
        // covariance (Pipeline is covariant in R), and the key assignment is type-safe.
        const updatedBranches: Partial<Record<TBranch, Pipeline<TIntermediate, TOutput, C, RBranch | R2>>> = {
            ...this.branches,
        }
        updatedBranches[branchName] = branchPipeline
        return new BranchingPipelineBuilder(this.decisionFn, this.previousPipeline, updatedBranches)
    }

    build(
        this: BranchingPipelineBuilder<TInput, TIntermediate, TOutput, C, TBranch, never, RPrev, RBranch>
    ): Pipeline<TInput, TOutput, C, RPrev | RBranch> {
        return new BranchingPipeline(this.decisionFn, this.branches, this.previousPipeline)
    }
}
