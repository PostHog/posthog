import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { isOkResult } from './results'

export class SequentialBatchPipeline<TInput, TIntermediate, TOutput> implements BatchPipeline<TInput, TOutput> {
    constructor(
        private currentPipeline: Pipeline<TIntermediate, TOutput>,
        private previousPipeline: BatchPipeline<TInput, TIntermediate>
    ) {}

    feed(elements: BatchPipelineResultWithContext<TInput>): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput> | null> {
        const previousResults = await this.previousPipeline.next()
        if (previousResults === null) {
            return null
        }

        const results: PipelineResultWithContext<TOutput>[] = []
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
