import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { BranchFunction, BranchingBatchPipeline } from './branching-batch-pipeline'
import { GatheringBatchPipeline } from './gathering-batch-pipeline'
import { Pipeline, PipelineContext, PipelineResultWithContext } from './pipeline.interface'
import { isOkResult } from './results'

export class ConcurrentBatchProcessingPipeline<TInput, TIntermediate, TOutput, C = PipelineContext>
    implements BatchPipeline<TInput, TOutput, C>
{
    private promiseQueue: Promise<PipelineResultWithContext<TOutput, C>>[] = []

    constructor(
        private processor: Pipeline<TIntermediate, TOutput, C>,
        private previousPipeline: BatchPipeline<TInput, TIntermediate, C>
    ) {}

    feed(elements: BatchPipelineResultWithContext<TInput, C>): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, C> | null> {
        const previousResults = await this.previousPipeline.next()

        if (previousResults !== null) {
            previousResults.forEach((resultWithContext) => {
                const result = resultWithContext.result
                if (isOkResult(result)) {
                    const promise = this.processor.process(resultWithContext)
                    this.promiseQueue.push(promise)
                } else {
                    this.promiseQueue.push(
                        Promise.resolve({
                            result: result,
                            context: resultWithContext.context,
                        })
                    )
                }
            })
        }

        const promise = this.promiseQueue.shift()
        if (promise === undefined) {
            return null
        }

        const resultWithContext = await promise
        return [resultWithContext]
    }

    gather(): GatheringBatchPipeline<TInput, TOutput, C> {
        return new GatheringBatchPipeline(this)
    }

    branch<TBranched, COut extends C = C>(
        branchFn: BranchFunction<TOutput, TBranched, C, COut>,
        truePipeline: BatchPipeline<TBranched, TOutput, COut>,
        falsePipeline: BatchPipeline<TOutput, TOutput, C>
    ): BranchingBatchPipeline<TInput, TOutput, TBranched, TOutput, C, COut> {
        return new BranchingBatchPipeline(this, branchFn, truePipeline, falsePipeline)
    }
}
