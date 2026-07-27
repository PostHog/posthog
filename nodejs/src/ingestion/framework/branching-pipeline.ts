import { OkResultWithContext, Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { dlq, isOkResult } from './results'

export type BranchDecisionFn<TIntermediate, TBranch extends string> = (value: TIntermediate) => TBranch

/**
 * Pipeline that routes processing to different branch pipelines based on a decision function.
 * First processes through the previous pipeline, then evaluates the decision function to get a branch name,
 * and finally processes through that branch's pipeline.
 *
 * RPrev is the redirect type from the previous pipeline.
 * RBranch is the union of redirect types from all branches.
 */
export class BranchingPipeline<
    TInput,
    TIntermediate,
    TOutput,
    C,
    TBranch extends string,
    RPrev extends string = never,
    RBranch extends string = never,
> implements Pipeline<TInput, TOutput, C, RPrev | RBranch>
{
    constructor(
        private decisionFn: BranchDecisionFn<TIntermediate, TBranch>,
        private branches: Partial<Record<TBranch, Pipeline<TIntermediate, TOutput, C, RBranch>>>,
        private previousPipeline: Pipeline<TInput, TIntermediate, C, RPrev>
    ) {}

    async process(
        input: OkResultWithContext<TInput, C>
    ): Promise<PipelineResultWithContext<TOutput, C, RPrev | RBranch>> {
        const previousResultWithContext = await this.previousPipeline.process(input)

        if (!isOkResult(previousResultWithContext.result)) {
            return {
                result: previousResultWithContext.result,
                context: previousResultWithContext.context,
            }
        }

        const branchName = this.decisionFn(previousResultWithContext.result.value)

        const branchPipeline = this.branches[branchName]
        if (!branchPipeline) {
            return {
                result: dlq(
                    `Unknown branch: ${branchName}`,
                    new Error(`Branch '${branchName}' not found in branching pipeline`)
                ),
                context: previousResultWithContext.context,
            }
        }

        return branchPipeline.process({
            result: previousResultWithContext.result,
            context: previousResultWithContext.context,
        })
    }
}
