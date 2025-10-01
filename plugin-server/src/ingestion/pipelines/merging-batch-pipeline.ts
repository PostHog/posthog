import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { BranchingBatchPipeline } from './branching-batch-pipeline'
import { GatheringBatchPipeline } from './gathering-batch-pipeline'
import { PipelineContext } from './pipeline.interface'

export class MergingBatchPipeline<
    TInput,
    TIntermediate,
    TBranched,
    TOutput,
    CInput = PipelineContext,
    COutputTrue extends CInput = CInput,
> implements BatchPipeline<TInput, TOutput, CInput>
{
    constructor(
        private branchingPipeline: BranchingBatchPipeline<
            TInput,
            TIntermediate,
            TBranched,
            TOutput,
            CInput,
            COutputTrue
        >
    ) {}

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): void {
        this.branchingPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, CInput> | null> {
        const result = await this.branchingPipeline.next()
        if (result === null) {
            return null
        }
        return result.results
    }

    gather(): GatheringBatchPipeline<TInput, TOutput, CInput> {
        return new GatheringBatchPipeline(this)
    }
}
