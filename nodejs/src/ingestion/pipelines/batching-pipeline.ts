import { BatchPipeline, BatchPipelineResultWithContext, FeedResult } from './batch-pipeline.interface'
import { PipelineResultWithContext } from './pipeline.interface'

export interface BatchingContext {
    messageId: number
}

export interface BatchResult<T> {
    value: T
    sideEffects: Promise<unknown>[]
}

export interface BatchingPipelineOptions {
    concurrentBatches: number
}

const BATCHING_PIPELINE_DEFAULTS: BatchingPipelineOptions = {
    concurrentBatches: 1,
}

interface TrackedBatch<TOutput, CBatch, CSubOut> {
    batchContext: CBatch
    messageIds: number[]
    inflight: Set<number>
    results: Map<number, PipelineResultWithContext<TOutput, CSubOut>>
    beforeSideEffects: Promise<unknown>[]
}

/**
 * Pipeline step that tracks which messages belong to which feed() call (batch).
 * When all messages from a batch have exited the pipeline, fires afterBatch
 * with the results in their original feed order within the batch.
 *
 * Each call to feed() is a distinct batch. The collector assigns a monotonic
 * messageId to each element via the context. As results come out of next(),
 * the collector matches them to their batch and fires hooks.
 *
 * Lifecycle:
 * - feed() runs beforeBatch which returns mapped elements and side effects.
 *   Elements are tagged with messageId, then fed to the sub-pipeline.
 * - next() collects results. When all messages in a batch complete, calls
 *   afterBatch with the batchContext and ordered results, then returns a
 *   BatchResult with concatenated side effects.
 *
 * Ordering guarantees:
 * - Messages within a completed batch are returned in their original feed() order
 * - Batches themselves are returned in completion order, NOT submission order.
 * - next() loops internally until a batch completes or the sub-pipeline drains.
 * - next() returns null when all batches are drained and no buffered results remain.
 *
 * Type parameters:
 * - TInput/TOutput: value types flowing through the pipeline
 * - CInput: context type accepted by feed() (without messageId)
 * - CBatch: opaque batch context passed to hooks
 * - CSubIn: context type fed to the sub-pipeline after beforeBatch maps elements.
 *   Must extend CInput & BatchingContext.
 * - CSubOut: context type returned by the sub-pipeline.
 *   Must extend BatchingContext (messageId flows through the sub-pipeline).
 */
export class BatchingPipeline<
    TInput,
    TOutput,
    CInput,
    CBatch,
    CSubIn extends CInput & BatchingContext,
    CSubOut extends BatchingContext,
> {
    private nextBatchId = 0
    private nextMessageId = 0
    private batches = new Map<number, TrackedBatch<TOutput, CBatch, CSubOut>>()
    private messageIdToBatchId = new Map<number, number>()
    private completedResults: BatchResult<BatchPipelineResultWithContext<TOutput, CSubOut>>[] = []

    private options: BatchingPipelineOptions

    constructor(
        private subPipeline: BatchPipeline<TInput, TOutput, CSubIn, CSubOut>,
        private hooks: {
            beforeBatch: (
                batchContext: CBatch,
                elements: BatchPipelineResultWithContext<TInput, CInput>,
                batchId: number
            ) => BatchResult<BatchPipelineResultWithContext<TInput, CInput>>
            afterBatch: (
                batchContext: CBatch,
                results: BatchPipelineResultWithContext<TOutput, CSubOut>,
                batchId: number
            ) => BatchResult<void> | Promise<BatchResult<void>>
        },
        options?: Partial<BatchingPipelineOptions>
    ) {
        this.options = { ...BATCHING_PIPELINE_DEFAULTS, ...options }
    }

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>, batchContext: CBatch): FeedResult {
        if (this.batches.size >= this.options.concurrentBatches) {
            return { ok: false, reason: `at concurrent batch capacity (${this.options.concurrentBatches})` }
        }

        const batchId = this.nextBatchId++

        const beforeResult = this.hooks.beforeBatch(batchContext, elements, batchId)

        const messageIds: number[] = []
        const inflight = new Set<number>()

        const taggedElements = beforeResult.value.map((element) => {
            const messageId = this.nextMessageId++
            messageIds.push(messageId)
            inflight.add(messageId)
            this.messageIdToBatchId.set(messageId, batchId)

            return {
                result: element.result,
                context: {
                    ...element.context,
                    messageId,
                },
            }
        }) as unknown as BatchPipelineResultWithContext<TInput, CSubIn>

        this.batches.set(batchId, {
            batchContext,
            messageIds,
            inflight,
            results: new Map(),
            beforeSideEffects: beforeResult.sideEffects,
        })

        this.subPipeline.feed(taggedElements)
        return { ok: true }
    }

    async next(): Promise<BatchResult<BatchPipelineResultWithContext<TOutput, CSubOut>> | null> {
        if (this.completedResults.length > 0) {
            return this.completedResults.shift()!
        }

        while (true) {
            const result = await this.subPipeline.next()
            if (result === null) {
                if (this.batches.size > 0) {
                    throw new Error(
                        `batching_pipeline sub-pipeline returned null with ${this.batches.size} in-flight batches and ${this.messageIdToBatchId.size} in-flight messages`
                    )
                }
                return null
            }

            for (const resultWithContext of result) {
                const messageId = resultWithContext.context.messageId
                const batchId = this.messageIdToBatchId.get(messageId)
                if (batchId === undefined) {
                    throw new Error(`batching_pipeline received result with unknown messageId ${messageId}`)
                }

                const batch = this.batches.get(batchId)
                if (!batch) {
                    throw new Error(
                        `batching_pipeline has batchId mapping but batch ${batchId} is missing for messageId ${messageId}`
                    )
                }

                batch.inflight.delete(messageId)
                batch.results.set(messageId, resultWithContext)

                if (batch.inflight.size === 0) {
                    const orderedResults = batch.messageIds.map((id) => batch.results.get(id)!)
                    this.batches.delete(batchId)
                    for (const id of batch.messageIds) {
                        this.messageIdToBatchId.delete(id)
                    }
                    const afterResult = await this.hooks.afterBatch(batch.batchContext, orderedResults, batchId)
                    const sideEffects = [...batch.beforeSideEffects, ...afterResult.sideEffects]
                    this.completedResults.push({ value: orderedResults, sideEffects })
                }
            }

            if (this.completedResults.length > 0) {
                return this.completedResults.shift()!
            }
        }
    }
}
