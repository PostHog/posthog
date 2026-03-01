import { logger } from '../../utils/logger'
import { BatchPipeline, BatchPipelineResultWithContext, FeedResult } from './batch-pipeline.interface'
import { PipelineResultWithContext } from './pipeline.interface'

export interface BatchingContext {
    messageId: number
}

export interface BeforeBatchResult<CBatch, TInput, C> {
    batchContext: CBatch
    elements: BatchPipelineResultWithContext<TInput, C>
}

export function batch<CBatch, TInput, C>(
    elements: BatchPipelineResultWithContext<TInput, C>,
    batchContext: CBatch
): BeforeBatchResult<CBatch, TInput, C> {
    return { batchContext, elements }
}

interface TrackedBatch<TOutput, CBatch, CSubOut> {
    batchContext: CBatch
    messageIds: number[]
    inflight: Set<number>
    results: Map<number, PipelineResultWithContext<TOutput, CSubOut>>
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
 * - feed() tags elements with messageId, then calls beforeBatch which returns
 *   a batchContext (opaque data carried per-batch) and mapped elements
 *   (e.g. add per-batch stores to context). The mapped elements are fed to the
 *   sub-pipeline.
 * - next() collects results. When all messages in a batch complete, calls
 *   afterBatch with the batchContext and ordered results, then returns results.
 *
 * Ordering guarantees:
 * - Messages within a completed batch are returned in their original feed() order
 * - Batches themselves are returned in completion order, NOT submission order.
 *   If batch 1 completes before batch 0, batch 1's results appear first in next().
 * - next() returns [] when the sub-pipeline produced results but no batch completed yet,
 *   and null when the sub-pipeline is fully drained.
 *
 * Type parameters:
 * - TInput/TOutput: value types flowing through the pipeline
 * - CInput: context type accepted by feed() (without messageId)
 * - CBatch: opaque batch context returned by beforeBatch, passed to afterBatch
 * - CSubIn: context type fed to the sub-pipeline after beforeBatch maps elements.
 *   Must extend CInput & BatchingContext. beforeBatch maps from
 *   CInput & BatchingContext → CSubIn (e.g. to add per-batch stores).
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
> implements BatchPipeline<TInput, TOutput, CInput, CSubOut>
{
    private nextBatchId = 0
    private nextMessageId = 0
    private batches = new Map<number, TrackedBatch<TOutput, CBatch, CSubOut>>()
    private messageIdToBatchId = new Map<number, number>()

    constructor(
        private subPipeline: BatchPipeline<TInput, TOutput, CSubIn, CSubOut>,
        private hooks: {
            beforeBatch: (
                elements: BatchPipelineResultWithContext<TInput, CInput & BatchingContext>,
                batchId: number
            ) => { batchContext: CBatch; elements: BatchPipelineResultWithContext<TInput, CSubIn> }
            afterBatch: (
                batchContext: CBatch,
                results: BatchPipelineResultWithContext<TOutput, CSubOut>,
                batchId: number
            ) =>
                | BatchPipelineResultWithContext<TOutput, CSubOut>
                | Promise<BatchPipelineResultWithContext<TOutput, CSubOut>>
        }
    ) {}

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): FeedResult {
        const batchId = this.nextBatchId++
        const messageIds: number[] = []
        const inflight = new Set<number>()

        const taggedElements: BatchPipelineResultWithContext<TInput, CInput & BatchingContext> = elements.map(
            (element) => {
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
            }
        )

        const { batchContext, elements: mappedElements } = this.hooks.beforeBatch(taggedElements, batchId)

        this.batches.set(batchId, {
            batchContext,
            messageIds,
            inflight,
            results: new Map(),
        })

        this.subPipeline.feed(mappedElements)
        return { ok: true }
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, CSubOut> | null> {
        const result = await this.subPipeline.next()
        if (result === null) {
            if (this.batches.size > 0) {
                logger.error('🪣', 'batching_pipeline sub-pipeline returned null with in-flight batches', {
                    inflightBatches: this.batches.size,
                    inflightMessages: this.messageIdToBatchId.size,
                })
            }
            return null
        }

        const completedBatchResults: PipelineResultWithContext<TOutput, CSubOut>[] = []

        for (const resultWithContext of result) {
            const messageId = resultWithContext.context.messageId
            const batchId = this.messageIdToBatchId.get(messageId)
            if (batchId === undefined) {
                logger.error('🪣', 'batching_pipeline received result with unknown messageId', { messageId })
                continue
            }

            const batch = this.batches.get(batchId)
            if (!batch) {
                logger.error('🪣', 'batching_pipeline has batchId mapping but batch is missing', {
                    messageId,
                    batchId,
                })
                continue
            }

            batch.inflight.delete(messageId)
            batch.results.set(messageId, resultWithContext)

            if (batch.inflight.size === 0) {
                const orderedResults = batch.messageIds.map((id) => batch.results.get(id)!)
                this.batches.delete(batchId)
                for (const id of batch.messageIds) {
                    this.messageIdToBatchId.delete(id)
                }
                const mappedResults = await this.hooks.afterBatch(batch.batchContext, orderedResults, batchId)
                completedBatchResults.push(...mappedResults)
            }
        }

        return completedBatchResults
    }
}
