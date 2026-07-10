import { ChunkPipeline, ChunkPipelineResultWithContext, OkResultWithContext } from './chunk-pipeline.interface'

export class BufferingBatchPipeline<TInput, CInput, R extends string = never>
    implements ChunkPipeline<TInput, TInput, CInput, CInput, R>
{
    private buffer: ChunkPipelineResultWithContext<TInput, CInput, R> = []

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.buffer.push(...elements)
    }

    async next(): Promise<ChunkPipelineResultWithContext<TInput, CInput, R> | null> {
        if (this.buffer.length === 0) {
            return null
        }
        const results = this.buffer
        this.buffer = []
        return Promise.resolve(results)
    }
}
