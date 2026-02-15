import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { Pipeline, PipelineContext, PipelineResultWithContext } from './pipeline.interface'
import { isOkResult } from './results'

export class ConcurrentBatchProcessingPipeline<
    TInput,
    TIntermediate,
    TOutput,
    CInput = PipelineContext,
    COutput = CInput,
> implements BatchPipeline<TInput, TOutput, CInput, COutput>
{
    private promiseQueue: Promise<PipelineResultWithContext<TOutput, COutput>>[] = []

    constructor(
        private processor: Pipeline<TIntermediate, TOutput, COutput>,
        private previousPipeline: BatchPipeline<TInput, TIntermediate, CInput, COutput>
    ) {}

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput> | null> {
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
}
