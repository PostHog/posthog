import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'

export class GatheringBatchPipeline<TInput, TOutput, CInput, COutput = CInput>
    implements BatchPipeline<TInput, TOutput, CInput, COutput>
{
    constructor(private subPipeline: BatchPipeline<TInput, TOutput, CInput, COutput>) {}

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): void {
        this.subPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput> | null> {
        const allResults: BatchPipelineResultWithContext<TOutput, COutput> = []

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
