import { BatchPipeline, BatchPipelineResultWithContext, OkResultWithContext } from './batch-pipeline.interface'

export class GatheringBatchPipeline<TInput, TOutput, CInput, COutput = CInput, R extends string = never>
    implements BatchPipeline<TInput, TOutput, CInput, COutput, R>
{
    constructor(private subPipeline: BatchPipeline<TInput, TOutput, CInput, COutput, R>) {}

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.subPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput, R> | null> {
        const allResults: BatchPipelineResultWithContext<TOutput, COutput, R> = []

        let result = await this.subPipeline.next()
        while (result !== null) {
            result.forEach((resultWithContext) => {
                allResults.push(resultWithContext)
            })
            result = await this.subPipeline.next()
        }

        if (allResults.length === 0) {
            return null
        }

        return allResults
    }
}
