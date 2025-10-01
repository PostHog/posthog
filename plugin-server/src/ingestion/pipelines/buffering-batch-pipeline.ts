import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { ConcurrentBatchProcessingPipeline } from './concurrent-batch-pipeline'
import { Pipeline } from './pipeline.interface'
import { SequentialBatchPipeline } from './sequential-batch-pipeline'

export class BufferingBatchPipeline<TInput, C> implements BatchPipeline<TInput, TInput, C> {
    private buffer: BatchPipelineResultWithContext<TInput, C> = []

    feed(elements: BatchPipelineResultWithContext<TInput, C>): void {
        this.buffer.push(...elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TInput, C> | null> {
        if (this.buffer.length === 0) {
            return null
        }
        const results = this.buffer
        this.buffer = []
        return Promise.resolve(results)
    }

    pipeConcurrently<TOutput>(
        processor: Pipeline<TInput, TOutput, C>
    ): ConcurrentBatchProcessingPipeline<TInput, TInput, TOutput, C> {
        return new ConcurrentBatchProcessingPipeline(processor, this)
    }

    pipeSequentially<TOutput>(
        processor: Pipeline<TInput, TOutput, C>
    ): SequentialBatchPipeline<TInput, TInput, TOutput, C> {
        return new SequentialBatchPipeline(processor, this)
    }
}
