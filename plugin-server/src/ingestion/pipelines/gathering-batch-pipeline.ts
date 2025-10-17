import { BaseBatchPipeline, BatchProcessingStep } from './base-batch-pipeline'
import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { PipelineContext } from './pipeline.interface'
import { isOkResult, ok } from './results'

export class GatheringBatchPipeline<TInput, TOutput, CInput = PipelineContext, COutput = CInput>
    implements BatchPipeline<TInput, TOutput, CInput, COutput>
{
    constructor(private subPipeline: BatchPipeline<TInput, TOutput, CInput, COutput>) {}

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): void {
        this.subPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput> | null> {
        const allResults: BatchPipelineResultWithContext<TOutput, COutput> = []

        // Loop and collect all results from sub-pipeline
        let result = await this.subPipeline.next()

        while (result !== null) {
            // Collect all results in order, preserving context
            result.forEach((resultWithContext) => {
                if (isOkResult(resultWithContext.result)) {
                    allResults.push({
                        result: ok(resultWithContext.result.value),
                        context: resultWithContext.context,
                    })
                } else {
                    allResults.push(resultWithContext)
                }
            })

            result = await this.subPipeline.next()
        }

        // Return all collected results, or null if no results
        if (allResults.length === 0) {
            return null
        }

        return allResults
    }

    pipeBatch<U>(step: BatchProcessingStep<TOutput, U>): BaseBatchPipeline<TInput, TOutput, U, CInput, COutput> {
        return new BaseBatchPipeline(step, this)
    }
}
