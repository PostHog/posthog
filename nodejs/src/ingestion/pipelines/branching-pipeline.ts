import { Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { dlq, isOkResult } from './results'

export type BranchDecisionFn<TIntermediate, TBranch extends string> = (value: TIntermediate) => TBranch

/**
 * Pipeline that routes processing to different branch pipelines based on a decision function.
 * First processes through the previous pipeline, then evaluates the decision function to get a branch name,
 * and finally processes through that branch's pipeline.
 */
export class BranchingPipeline<TInput, TIntermediate, TOutput, C, TBranch extends string>
    implements Pipeline<TInput, TOutput, C>
{
    constructor(
        private decisionFn: BranchDecisionFn<TIntermediate, TBranch>,
        private branches: Record<TBranch, Pipeline<TIntermediate, TOutput, C>>,
        private previousPipeline: Pipeline<TInput, TIntermediate, C>
    ) {}

    async process(input: PipelineResultWithContext<TInput, C>): Promise<PipelineResultWithContext<TOutput, C>> {
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

        return await branchPipeline.process(previousResultWithContext)
    }
}
