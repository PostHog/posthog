import { BaseBatchPipeline, BatchProcessingStep } from './base-batch-pipeline'
import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { PipelineContext } from './pipeline.interface'
import { isOkResult, ok } from './results'

export class GatheringBatchPipeline<TInput, TOutput, C = PipelineContext> implements BatchPipeline<TInput, TOutput, C> {
    constructor(private subPipeline: BatchPipeline<TInput, TOutput, C>) {}

    feed(elements: BatchPipelineResultWithContext<TInput, C>): void {
        this.subPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, C> | null> {
        const allResults: BatchPipelineResultWithContext<TOutput, C> = []

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

    pipeBatch<U>(step: BatchProcessingStep<TOutput, U>): BaseBatchPipeline<TInput, TOutput, U, C> {
        return new BaseBatchPipeline(step, this)
    }
}
