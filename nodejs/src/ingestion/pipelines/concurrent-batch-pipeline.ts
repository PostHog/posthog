import { BatchPipeline, BatchPipelineResultWithContext, OkResultWithContext } from './batch-pipeline.interface'
import { Pipeline, PipelineContext, PipelineResultWithContext } from './pipeline.interface'
import { isOkResult } from './results'

export class ConcurrentBatchProcessingPipeline<
    TInput,
    TIntermediate,
    TOutput,
    CInput = PipelineContext,
    COutput = CInput,
    RPrev extends string = never,
    RStep extends string = never,
> implements BatchPipeline<TInput, TOutput, CInput, COutput, RPrev | RStep>
{
    private promiseQueue: Promise<PipelineResultWithContext<TOutput, COutput, RPrev | RStep>>[] = []

    constructor(
        private processor: Pipeline<TIntermediate, TOutput, COutput, RStep>,
        private previousPipeline: BatchPipeline<TInput, TIntermediate, CInput, COutput, RPrev>
    ) {}

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput, RPrev | RStep> | null> {
        const previousResults = await this.previousPipeline.next()

        if (previousResults !== null) {
            previousResults.forEach((resultWithContext) => {
                if (isOkResult(resultWithContext.result)) {
                    const promise = this.processor.process({
                        result: resultWithContext.result,
                        context: resultWithContext.context,
                    })
                    this.promiseQueue.push(promise)
                } else {
                    this.promiseQueue.push(
                        Promise.resolve({
                            result: resultWithContext.result,
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
