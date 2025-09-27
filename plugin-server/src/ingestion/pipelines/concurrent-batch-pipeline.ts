import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { GatheringBatchPipeline } from './gathering-batch-pipeline'
import { Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { isOkResult } from './results'

export class ConcurrentBatchProcessingPipeline<TInput, TIntermediate, TOutput>
    implements BatchPipeline<TInput, TOutput>
{
    private promiseQueue: Promise<PipelineResultWithContext<TOutput>>[] = []

    constructor(
        private processor: Pipeline<TIntermediate, TOutput>,
        private previousPipeline: BatchPipeline<TInput, TIntermediate>
    ) {}

    feed(elements: BatchPipelineResultWithContext<TInput>): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput> | null> {
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

    gather(): GatheringBatchPipeline<TInput, TOutput> {
        return new GatheringBatchPipeline(this)
    }
}
