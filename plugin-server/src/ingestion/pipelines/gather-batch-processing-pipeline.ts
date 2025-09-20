import { BatchProcessingStep, SequentialBatchProcessingPipeline } from './batch-processing-pipeline'
import { BatchProcessingPipeline, BatchProcessingResult, isSuccessResult, success } from './pipeline-types'

export class GatherBatchProcessingPipeline<TInput, TOutput> implements BatchProcessingPipeline<TInput, TOutput> {
    constructor(private subPipeline: BatchProcessingPipeline<TInput, TOutput>) {}

    feed(elements: BatchProcessingResult<TInput>): void {
        this.subPipeline.feed(elements)
    }

    async next(): Promise<BatchProcessingResult<TOutput> | null> {
        const allResults: BatchProcessingResult<TOutput> = []

        // Loop and collect all results from sub-pipeline
        let result = await this.subPipeline.next()

        while (result !== null) {
            // Collect all results in order, preserving context
            result.forEach((resultWithContext) => {
                if (isSuccessResult(resultWithContext.result)) {
                    allResults.push({
                        result: success(resultWithContext.result.value),
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

    pipeBatch<U>(step: BatchProcessingStep<TOutput, U>): SequentialBatchProcessingPipeline<TInput, TOutput, U> {
        return SequentialBatchProcessingPipeline.from(step, this)
    }
}
