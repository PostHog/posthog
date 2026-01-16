import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { isOkResult } from './results'

export type GroupingFunction<TInput, TKey> = (input: TInput) => TKey

/**
 * A batch pipeline that groups inputs by a key and processes each group concurrently.
 * Within each group, items are processed sequentially through the provided pipeline.
 *
 * Ordering guarantees:
 * - Items within the same group are always processed in order, even across multiple next() calls
 * - If new items arrive for a group that's currently processing, they're queued and processed
 *   after the current batch completes
 * - Results are returned unordered between groups - as each group completes processing,
 *   its results are made available
 */
export class ConcurrentlyGroupingBatchPipeline<TInput, TIntermediate, TOutput, TKey, CInput, COutput = CInput>
    implements BatchPipeline<TInput, TOutput, CInput, COutput>
{
    // Queue of items waiting to be processed for each group
    private groupQueues: Map<TKey, PipelineResultWithContext<TIntermediate, COutput>[]> = new Map()

    // Promise for the currently processing batch for each group (if any)
    private activeProcessing: Map<TKey, Promise<PipelineResultWithContext<TOutput, COutput>[]>> = new Map()

    // Completed result batches ready to be returned
    private completedResults: PipelineResultWithContext<TOutput, COutput>[][] = []

    constructor(
        private groupingFn: GroupingFunction<TIntermediate, TKey>,
        private processor: Pipeline<TIntermediate, TOutput, COutput>,
        private previousPipeline: BatchPipeline<TInput, TIntermediate, CInput, COutput>
    ) {}

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput> | null> {
        // Get more elements from the previous pipeline and route them to group queues
        const previousResults = await this.previousPipeline.next()
        if (previousResults !== null) {
            this.routeToGroups(previousResults)
        }

        // Start processing for any groups that have queued items and aren't currently processing
        this.startAvailableProcessing()

        // Return completed results if available
        const completed = this.pullCompletedResults()
        if (completed !== null) {
            return completed
        }

        // If there's active processing, wait for any to complete
        if (this.activeProcessing.size > 0) {
            await Promise.race(this.activeProcessing.values())
            return this.pullCompletedResults()
        }

        // Nothing left to process or return
        return null
    }

    private pullCompletedResults(): BatchPipelineResultWithContext<TOutput, COutput> | null {
        return this.completedResults.shift() ?? null
    }

    private routeToGroups(results: PipelineResultWithContext<TIntermediate, COutput>[]): void {
        const nonOkResults: PipelineResultWithContext<TOutput, COutput>[] = []

        for (const item of results) {
            if (isOkResult(item.result)) {
                const key = this.groupingFn(item.result.value)
                let queue = this.groupQueues.get(key)
                if (!queue) {
                    queue = []
                    this.groupQueues.set(key, queue)
                }
                queue.push(item)
            } else {
                // Accumulate non-OK results to return as a batch
                nonOkResults.push({
                    result: item.result,
                    context: item.context,
                })
            }
        }

        if (nonOkResults.length > 0) {
            this.completedResults.push(nonOkResults)
        }
    }

    private startAvailableProcessing(): void {
        for (const [key, queue] of this.groupQueues) {
            if (queue.length > 0 && !this.activeProcessing.has(key)) {
                // Delete the key to avoid memory leaks from unbounded keys
                this.groupQueues.delete(key)

                const processingPromise = this.processGroupSequentially(queue).then((results) => {
                    this.completedResults.push(results)
                    this.activeProcessing.delete(key)
                    return results
                })

                this.activeProcessing.set(key, processingPromise)
            }
        }
    }

    private async processGroupSequentially(
        items: PipelineResultWithContext<TIntermediate, COutput>[]
    ): Promise<PipelineResultWithContext<TOutput, COutput>[]> {
        const results: PipelineResultWithContext<TOutput, COutput>[] = []

        for (const item of items) {
            const result = await this.processor.process(item)
            results.push(result)
        }

        return results
    }
}
