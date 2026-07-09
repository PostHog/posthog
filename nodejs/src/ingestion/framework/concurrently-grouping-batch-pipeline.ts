import pLimit from 'p-limit'

import { BatchPipeline, BatchPipelineResultWithContext, OkResultWithContext } from './batch-pipeline.interface'
import { InterleavingBatchPipeline, PullOutcome } from './interleaving-batch-pipeline'
import { Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { ResettableSignal } from './resettable-signal'
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
 *
 * Failures poison the pipeline: if the upstream or a processor throws, results
 * from groups that already completed still drain, then next() rejects with that
 * error permanently.
 *
 * Synchronization (pulling upstream, draining completed groups, and staying
 * responsive to concurrent feeds so a parked drain isn't stranded) is handled by
 * {@link InterleavingBatchPipeline}. This class supplies the grouping policy:
 * routing into per-key queues, starting groups concurrently, and a per-group
 * completion signal so a parked drain wakes when ANY group finishes — including
 * a group that was started after the drain parked.
 */
export class ConcurrentlyGroupingBatchPipeline<
    TInput,
    TIntermediate,
    TOutput,
    TKey,
    CInput,
    COutput = CInput,
    RPrev extends string = never,
    RStep extends string = never,
> implements BatchPipeline<TInput, TOutput, CInput, COutput, RPrev | RStep>
{
    // Queue of items waiting to be processed for each group
    private groupQueues: Map<TKey, PipelineResultWithContext<TIntermediate, COutput, RPrev | RStep>[]> = new Map()

    // Promise for the currently processing batch for each group (if any)
    private activeProcessing: Map<TKey, Promise<PipelineResultWithContext<TOutput, COutput, RPrev | RStep>[]>> =
        new Map()

    // Completed result batches ready to be returned
    private completedResults: PipelineResultWithContext<TOutput, COutput, RPrev | RStep>[][] = []

    // Resolved whenever any group finishes (pushing to completedResults or
    // recording a failure), so a next() parked waiting on active groups wakes
    // even for a group that started after it parked.
    private groupCompleted = new ResettableSignal()

    // First processor error seen; once set, the pipeline is poisoned and every
    // next() that exhausts completed results rethrows it (mirroring the previous
    // behavior where a failed group's rejected promise re-rejected each drain).
    private failure: unknown = undefined

    private inner: InterleavingBatchPipeline<TInput, TOutput, CInput, COutput, RPrev | RStep>

    // Caps how many groups process at once. Null means unbounded (start every ready group).
    private readonly limit: ReturnType<typeof pLimit> | null

    constructor(
        private groupingFn: GroupingFunction<TIntermediate, TKey>,
        private processor: Pipeline<TIntermediate, TOutput, COutput, RStep>,
        private previousPipeline: BatchPipeline<TInput, TIntermediate, CInput, COutput, RPrev>,
        maxConcurrency?: number
    ) {
        this.limit = maxConcurrency !== undefined ? pLimit(maxConcurrency) : null
        this.inner = new InterleavingBatchPipeline<TInput, TOutput, CInput, COutput, RPrev | RStep>({
            onFeed: (elements) => this.previousPipeline.feed(elements),
            onSourcePull: () => this.routeFromPrevious(),
            onProcessPull: () => this.pullProcessed(),
        })
    }

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.inner.feed(elements)
    }

    next(): Promise<BatchPipelineResultWithContext<TOutput, COutput, RPrev | RStep> | null> {
        return this.inner.next()
    }

    /** Pull one upstream batch, route it into per-key queues, and start available groups. */
    private async routeFromPrevious(): Promise<PullOutcome<TOutput, COutput, RPrev | RStep>> {
        const previousResults = await this.previousPipeline.next()
        if (previousResults === null) {
            return { kind: 'drained' }
        }
        this.routeToGroups(previousResults)
        this.startAvailableProcessing()
        return { kind: 'drain' }
    }

    /** Emit the next completed group's results, parking until one finishes. */
    private async pullProcessed(): Promise<BatchPipelineResultWithContext<TOutput, COutput, RPrev | RStep> | null> {
        while (true) {
            const completed = this.completedResults.shift()
            if (completed !== undefined) {
                return completed
            }
            // Surface a processor failure only after draining everything that did
            // complete, so other groups' results are still returned first.
            if (this.failure !== undefined) {
                throw this.failure
            }
            if (this.activeProcessing.size === 0) {
                return null
            }
            this.groupCompleted.reset()
            await this.groupCompleted.wait()
        }
    }

    private routeToGroups(results: PipelineResultWithContext<TIntermediate, COutput, RPrev>[]): void {
        const nonOkResults: PipelineResultWithContext<TOutput, COutput, RPrev | RStep>[] = []

        for (const item of results) {
            if (isOkResult(item.result)) {
                const key = this.groupingFn(item.result.value)
                let queue = this.groupQueues.get(key)
                if (!queue) {
                    queue = []
                    this.groupQueues.set(key, queue)
                }
                queue.push({ result: item.result, context: item.context })
            } else {
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
        for (const key of this.groupQueues.keys()) {
            this.startGroupIfQueued(key)
        }
    }

    private startGroupIfQueued(key: TKey): void {
        const queue = this.groupQueues.get(key)
        if (!queue || queue.length === 0 || this.activeProcessing.has(key)) {
            return
        }
        this.groupQueues.delete(key)

        // The key is claimed in activeProcessing synchronously below, so per-key ordering holds even
        // when a group parks waiting for a concurrency permit.
        const run = this.limit
            ? this.limit(() => this.processGroupSequentially(queue))
            : this.processGroupSequentially(queue)
        const processingPromise = run.then(
            (results) => {
                this.completedResults.push(results)
                this.activeProcessing.delete(key)
                // The key is free again: start any items queued for it while it
                // was processing (preserves per-key ordering). Only this key can
                // have newly-startable items — items for other keys are started
                // when they arrive (routeFromPrevious) or by their own
                // completion — so a targeted O(1) restart suffices.
                this.startGroupIfQueued(key)
                this.groupCompleted.resolve()
                return results
            },
            (error: unknown) => {
                // Poison the pipeline. Keep the key in activeProcessing so
                // later items for it never start, and wake a parked
                // pullProcessed so it can rethrow.
                this.failure ??= error
                this.groupCompleted.resolve()
                return []
            }
        )

        this.activeProcessing.set(key, processingPromise)
    }

    private async processGroupSequentially(
        items: PipelineResultWithContext<TIntermediate, COutput, RPrev | RStep>[]
    ): Promise<PipelineResultWithContext<TOutput, COutput, RPrev | RStep>[]> {
        const results: PipelineResultWithContext<TOutput, COutput, RPrev | RStep>[] = []

        for (const item of items) {
            if (isOkResult(item.result)) {
                const result = await this.processor.process({
                    result: item.result,
                    context: item.context,
                })
                results.push(result)
            } else {
                results.push({
                    result: item.result,
                    context: item.context,
                })
            }
        }

        return results
    }
}
