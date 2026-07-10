import { ChunkPipeline, ChunkPipelineResultWithContext, OkResultWithContext } from './chunk-pipeline.interface'

export class GatheringBatchPipeline<TInput, TOutput, CInput, COutput = CInput, R extends string = never>
    implements ChunkPipeline<TInput, TOutput, CInput, COutput, R>
{
    constructor(private subPipeline: ChunkPipeline<TInput, TOutput, CInput, COutput, R>) {}

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.subPipeline.feed(elements)
    }

    async next(): Promise<ChunkPipelineResultWithContext<TOutput, COutput, R> | null> {
        const allResults: ChunkPipelineResultWithContext<TOutput, COutput, R> = []

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
