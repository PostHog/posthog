import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { PipelineContext } from './pipeline.interface'
import { PipelineResultOk, isOkResult } from './results'

export type ShardingFunction<T, C> = (resultWithContext: {
    result: PipelineResultOk<T>
    context: PipelineContext<C>
}) => number

/**
 * Pipeline that distributes work across multiple shards based on a hashing function.
 * Groups elements by hash modulo number of shards, feeds to shard pipelines,
 * and processes shards concurrently using promise racing.
 */
export class ShardingBatchPipeline<TInput, TIntermediate, TOutput, CInput, COutput = CInput>
    implements BatchPipeline<TInput, TOutput, CInput, COutput>
{
    private numShards: number
    private shardPromises: Map<number, Promise<BatchPipelineResultWithContext<TOutput, COutput> | null>>

    constructor(
        private shardingFn: ShardingFunction<TIntermediate, COutput>,
        private shardPipelines: BatchPipeline<TIntermediate, TOutput, COutput, COutput>[],
        private previousPipeline: BatchPipeline<TInput, TIntermediate, CInput, COutput>
    ) {
        this.numShards = shardPipelines.length
        this.shardPromises = new Map()
    }

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput> | null> {
        // Always try to feed shards from previous pipeline
        const previousResults = await this.previousPipeline.next()

        // Separate ok and non-ok results
        const nonOkResults: BatchPipelineResultWithContext<TIntermediate, COutput> = []
        const okResults: BatchPipelineResultWithContext<TIntermediate, COutput> = []

        if (previousResults !== null) {
            for (const resultWithContext of previousResults) {
                if (isOkResult(resultWithContext.result)) {
                    okResults.push(resultWithContext)
                } else {
                    nonOkResults.push(resultWithContext)
                }
            }

            // Only shard ok results
            if (okResults.length > 0) {
                // Group elements by shard without reordering
                const shardBatches: Map<number, BatchPipelineResultWithContext<TIntermediate, COutput>> = new Map()

                for (let i = 0; i < this.numShards; i++) {
                    shardBatches.set(i, [])
                }

                for (const resultWithContext of okResults) {
                    // TypeScript knows this is an ok result because we filtered above
                    const hash = this.shardingFn(
                        resultWithContext as {
                            result: PipelineResultOk<TIntermediate>
                            context: PipelineContext<COutput>
                        }
                    )
                    const shardIndex = hash % this.numShards
                    shardBatches.get(shardIndex)!.push(resultWithContext)
                }

                // Feed batches to each shard
                for (let i = 0; i < this.numShards; i++) {
                    const batch = shardBatches.get(i)!
                    if (batch.length > 0) {
                        this.shardPipelines[i].feed(batch)
                    }
                }
            }
        }

        // If we have non-ok results, return them immediately (cast them to TOutput type)
        if (nonOkResults.length > 0) {
            return nonOkResults as unknown as BatchPipelineResultWithContext<TOutput, COutput>
        }

        // For each shard that doesn't have a promise, call next and store the promise
        for (let i = 0; i < this.numShards; i++) {
            if (!this.shardPromises.has(i)) {
                this.shardPromises.set(i, this.shardPipelines[i].next())
            }
        }

        // Race shard promises until we get a non-null result or run out of promises
        while (this.shardPromises.size > 0) {
            const entries = Array.from(this.shardPromises.entries())
            const promises = entries.map(([shardId, promise]) => promise.then((result) => ({ result, shardId })))

            const { result, shardId } = await Promise.race(promises)

            // Remove the completed promise from the map
            this.shardPromises.delete(shardId)

            // If we got a non-null result, return it
            if (result !== null) {
                return result
            }
        }

        // All shards returned null
        return null
    }
}
