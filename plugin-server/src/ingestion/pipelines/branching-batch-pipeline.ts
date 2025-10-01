import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { MergingBatchPipeline } from './merging-batch-pipeline'
import { PipelineContext, PipelineResultWithContext } from './pipeline.interface'

export type BranchingBatchPipelineResult<TOutput, COutputTrue, COutputFalse> =
    | { match: true; results: BatchPipelineResultWithContext<TOutput, COutputTrue> }
    | { match: false; results: BatchPipelineResultWithContext<TOutput, COutputFalse> }

export type BranchFunction<TInput, TBranched, CInput, COutput> = (
    element: PipelineResultWithContext<TInput, CInput>
) => PipelineResultWithContext<TBranched, COutput> | null

export class BranchingBatchPipeline<
    TInput,
    TIntermediate,
    TBranched,
    TOutput,
    CInput = PipelineContext,
    COutputTrue extends CInput = CInput,
> {
    constructor(
        private subPipeline: BatchPipeline<TInput, TIntermediate, CInput>,
        private branchFn: BranchFunction<TIntermediate, TBranched, CInput, COutputTrue>,
        private truePipeline: BatchPipeline<TBranched, TOutput, COutputTrue>,
        private falsePipeline: BatchPipeline<TIntermediate, TOutput, CInput>
    ) {}

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): void {
        this.subPipeline.feed(elements)
    }

    async next(): Promise<BranchingBatchPipelineResult<TOutput, COutputTrue, CInput> | null> {
        const subResults = await this.subPipeline.next()
        if (subResults === null) {
            return null
        }

        const trueElements: PipelineResultWithContext<TBranched, COutputTrue>[] = []
        const falseElements: PipelineResultWithContext<TIntermediate, CInput>[] = []

        for (const element of subResults) {
            const branchResult = this.branchFn(element)
            if (branchResult !== null) {
                trueElements.push(branchResult)
            } else {
                falseElements.push(element)
            }
        }

        if (trueElements.length > 0) {
            this.truePipeline.feed(trueElements)
            const trueResults = await this.truePipeline.next()
            if (trueResults !== null) {
                return { match: true, results: trueResults }
            }
        }

        if (falseElements.length > 0) {
            this.falsePipeline.feed(falseElements)
            const falseResults = await this.falsePipeline.next()
            if (falseResults !== null) {
                return { match: false, results: falseResults }
            }
        }

        return null
    }

    merge(): MergingBatchPipeline<TInput, TIntermediate, TBranched, TOutput, CInput, COutputTrue> {
        return new MergingBatchPipeline(this)
    }
}
