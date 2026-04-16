import { BatchPipeline, BatchPipelineResultWithContext, OkResultWithContext } from './batch-pipeline.interface'
import { createOkContext } from './helpers'
import { Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { PipelineResult, isOkResult } from './results'

export type FeedResult = { ok: true } | { ok: false; reason: string }

export interface BatchingContext {
    messageId: number
}

export interface BeforeBatchInput<TInput, CInput> {
    elements: OkResultWithContext<TInput, CInput>[]
    batchId: number
}

export interface BeforeBatchOutput<TInput, CInput, CBatch> {
    elements: OkResultWithContext<TInput & CBatch, CInput>[]
    batchContext: CBatch
}

export interface AfterBatchInput<TOutput, COutput, CBatch, R extends string = never> {
    elements: BatchPipelineResultWithContext<TOutput, COutput, R>
    batchContext: CBatch
    batchId: number
}

export interface AfterBatchOutput<TOutput, COutput, CBatch, R extends string = never> {
    elements: BatchPipelineResultWithContext<TOutput, COutput, R>
    batchContext: CBatch
}

export type BeforeBatchStep<TInput, CInput, CBatch> = (
    input: BeforeBatchInput<TInput, CInput>
) => Promise<PipelineResult<BeforeBatchOutput<TInput, CInput, CBatch>>>

export type AfterBatchStep<TOutput, COutput, CBatch, R extends string = never> = (
    input: AfterBatchInput<TOutput, COutput, CBatch, R>
) => Promise<PipelineResult<AfterBatchOutput<TOutput, COutput, CBatch, R>>>

export interface BatchResult<T> {
    elements: T
    sideEffects?: Promise<unknown>[]
}

export interface BatchingPipelineOptions {
    concurrentBatches: number
}

const BATCHING_PIPELINE_DEFAULTS: BatchingPipelineOptions = {
    concurrentBatches: 1,
}

interface TrackedBatch<TOutput, CBatch, COutput, R extends string = never> {
    batchContext: CBatch
    messageIds: number[]
    inflight: Set<number>
    results: Map<number, PipelineResultWithContext<TOutput, COutput, R>>
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
 * - COutput: context type returned by the sub-pipeline.
 *   Must extend BatchingContext (messageId flows through the sub-pipeline).
 */
export class BatchingPipeline<
    TInput,
    TOutput,
    CInput,
    CBatch,
    COutput extends BatchingContext,
    R extends string = never,
> {
    private nextBatchId = 0
    private nextMessageId = 0
    private batches = new Map<number, TrackedBatch<TOutput, CBatch, COutput, R>>()
    private messageIdToBatchId = new Map<number, number>()
    private completedResults: BatchResult<BatchPipelineResultWithContext<TOutput, COutput, R>>[] = []

    private options: BatchingPipelineOptions

    constructor(
        private subPipeline: BatchPipeline<TInput & CBatch, TOutput, CInput & BatchingContext, COutput, R>,
        private beforePipeline: Pipeline<
            BeforeBatchInput<TInput, CInput>,
            BeforeBatchOutput<TInput, CInput, CBatch>,
            Record<string, never>
        >,
        private afterPipeline: Pipeline<
            AfterBatchInput<TOutput, COutput, CBatch, R>,
            AfterBatchOutput<TOutput, COutput, CBatch, R>,
            Record<string, never>
        >,
        options?: Partial<BatchingPipelineOptions>
    ) {
        this.options = { ...BATCHING_PIPELINE_DEFAULTS, ...options }
    }

    async feed(elements: OkResultWithContext<TInput, CInput>[]): Promise<FeedResult> {
        if (this.batches.size >= this.options.concurrentBatches) {
            return { ok: false, reason: `at concurrent batch capacity (${this.options.concurrentBatches})` }
        }

        const batchId = this.nextBatchId++

        const beforeInput: BeforeBatchInput<TInput, CInput> = { elements, batchId }
        const beforeResult = await this.beforePipeline.process(createOkContext(beforeInput, {}))

        if (!isOkResult(beforeResult.result)) {
            return { ok: false, reason: `beforeBatch hook returned non-ok result for batch ${batchId}` }
        }

        const { elements: mappedElements, batchContext } = beforeResult.result.value
        const beforeSideEffects = beforeResult.context.sideEffects

        const messageIds: number[] = []
        const inflight = new Set<number>()

        const taggedElements = mappedElements.map((element) => {
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
        })

        this.batches.set(batchId, {
            batchContext,
            messageIds,
            inflight,
            results: new Map(),
            beforeSideEffects,
        })

        this.subPipeline.feed(taggedElements)
        return { ok: true }
    }

    async next(): Promise<BatchResult<BatchPipelineResultWithContext<TOutput, COutput, R>> | null> {
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

                    const afterInput: AfterBatchInput<TOutput, COutput, CBatch, R> = {
                        elements: orderedResults,
                        batchContext: batch.batchContext,
                        batchId,
                    }
                    const afterResult = await this.afterPipeline.process(createOkContext(afterInput, {}))

                    if (!isOkResult(afterResult.result)) {
                        throw new Error(`batching_pipeline afterBatch hook returned non-ok result for batch ${batchId}`)
                    }

                    const afterSideEffects = afterResult.context.sideEffects
                    const sideEffects = [...batch.beforeSideEffects, ...afterSideEffects]
                    this.completedResults.push({ elements: afterResult.result.value.elements, sideEffects })
                }
            }

            if (this.completedResults.length > 0) {
                return this.completedResults.shift()!
            }
        }
    }
}
