import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { isOkResult } from './results'

export class SequentialBatchPipeline<TInput, TIntermediate, TOutput, C> implements BatchPipeline<TInput, TOutput, C> {
    constructor(
        private currentPipeline: Pipeline<TIntermediate, TOutput, C>,
        private previousPipeline: BatchPipeline<TInput, TIntermediate, C>
    ) {}

    feed(elements: BatchPipelineResultWithContext<TInput, C>): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, C> | null> {
        const previousResults = await this.previousPipeline.next()
        if (previousResults === null) {
            return null
        }

        const results: PipelineResultWithContext<TOutput, C>[] = []
        for (const resultWithContext of previousResults) {
            if (isOkResult(resultWithContext.result)) {
                const pipelineResult = await this.currentPipeline.process(resultWithContext)
                results.push(pipelineResult)
            } else {
                results.push({
                    result: resultWithContext.result,
                    context: resultWithContext.context,
                })
            }
        }

        // Return the processed results
        return results
    }
}
