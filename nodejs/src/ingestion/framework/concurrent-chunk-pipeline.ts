import pLimit from 'p-limit'

import { ChunkPipeline, ChunkPipelineResultWithContext, OkResultWithContext } from './chunk-pipeline.interface'
import { InterleavingBatchPipeline, PullOutcome } from './interleaving-batch-pipeline'
import { Pipeline, PipelineContext, PipelineResultWithContext } from './pipeline.interface'
import { isOkResult } from './results'

/**
 * Processes each item of a chunk concurrently, emitting results in input (FIFO)
 * order. Items start processing as soon as they're pulled from upstream; results
 * are emitted one at a time by awaiting the head of the queue.
 *
 * Pulling/enqueueing more upstream input is interleaved with awaiting the head
 * via {@link InterleavingBatchPipeline}, so a slow head no longer blocks newly
 * fed items from starting to process (it only delays their *emission*, which
 * stays FIFO by design).
 *
 * Failures poison the pipeline: if the upstream or a processor throws, items
 * already in flight still drain in FIFO order, then next() rejects with that
 * error permanently.
 */
export class ConcurrentChunkProcessingPipeline<
    TInput,
    TIntermediate,
    TOutput,
    CInput = PipelineContext,
    COutput = CInput,
    RPrev extends string = never,
    RStep extends string = never,
> implements ChunkPipeline<TInput, TOutput, CInput, COutput, RPrev | RStep>
{
    private promiseQueue: Promise<PipelineResultWithContext<TOutput, COutput, RPrev | RStep>>[] = []
    private inner: InterleavingBatchPipeline<TInput, TOutput, CInput, COutput, RPrev | RStep>

    // Caps how many items process at once. Null means unbounded (start every item as it's pulled).
    private readonly limit: ReturnType<typeof pLimit> | null

    constructor(
        private processor: Pipeline<TIntermediate, TOutput, COutput, RStep>,
        private previousPipeline: ChunkPipeline<TInput, TIntermediate, CInput, COutput, RPrev>,
        maxConcurrency?: number
    ) {
        this.limit = maxConcurrency !== undefined ? pLimit(maxConcurrency) : null
        this.inner = new InterleavingBatchPipeline<TInput, TOutput, CInput, COutput, RPrev | RStep>({
            onFeed: (elements) => this.previousPipeline.feed(elements),
            onSourcePull: () => this.enqueueFromPrevious(),
            onProcessPull: () => this.dequeueProcessed(),
        })
    }

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.inner.feed(elements)
    }

    next(): Promise<ChunkPipelineResultWithContext<TOutput, COutput, RPrev | RStep> | null> {
        return this.inner.next()
    }

    /** Pull one upstream chunk and start processing every item concurrently. */
    private async enqueueFromPrevious(): Promise<PullOutcome<TOutput, COutput, RPrev | RStep>> {
        const previousResults = await this.previousPipeline.next()
        if (previousResults === null) {
            return { kind: 'drained' }
        }

        for (const resultWithContext of previousResults) {
            if (isOkResult(resultWithContext.result)) {
                // Capture the narrowed ok result before the closure, which wouldn't re-narrow it.
                const okResult = resultWithContext.result
                const context = resultWithContext.context
                const process = () => this.processor.process({ result: okResult, context })
                // p-limit is FIFO, so the head of promiseQueue (pushed first) always acquires a permit
                // first — it can never park behind a later item, keeping emission order intact.
                this.promiseQueue.push(this.limit ? this.limit(process) : process())
            } else {
                this.promiseQueue.push(
                    Promise.resolve({ result: resultWithContext.result, context: resultWithContext.context })
                )
            }
        }

        return { kind: 'drain' }
    }

    /** Emit the next processed item in FIFO order, or null when the queue is empty. */
    private async dequeueProcessed(): Promise<ChunkPipelineResultWithContext<TOutput, COutput, RPrev | RStep> | null> {
        const promise = this.promiseQueue.shift()
        if (promise === undefined) {
            return null
        }
        return [await promise]
    }
}
