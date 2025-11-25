import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { isOkResult } from './results'

export class SequentialBatchPipeline<TInput, TIntermediate, TOutput, CInput, COutput = CInput>
    implements BatchPipeline<TInput, TOutput, CInput, COutput>
{
    constructor(
        private currentPipeline: Pipeline<TIntermediate, TOutput, COutput>,
        private previousPipeline: BatchPipeline<TInput, TIntermediate, CInput, COutput>
    ) {}

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput> | null> {
        const previousResults = await this.previousPipeline.next()
        if (previousResults === null) {
            return null
        }

        const results: PipelineResultWithContext<TOutput, COutput>[] = []
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
