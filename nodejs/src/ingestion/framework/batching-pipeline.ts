import pLimit from 'p-limit'

import { BatchPipeline, BatchPipelineResultWithContext, OkResultWithContext } from './batch-pipeline.interface'
import { createOkContext } from './helpers'
import { Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { PipelineResult, isOkResult } from './results'

export type FeedRejectionKind = 'at_capacity' | 'before_batch_failed'

export type FeedResult = { ok: true } | { ok: false; kind: FeedRejectionKind; reason: string }

export interface BatchingContext {
    messageId: number
}

export interface BeforeBatchInput<TInput, CInput, CBatch = Record<never, object>> {
    elements: OkResultWithContext<TInput, CInput>[]
    batchContext: { batchId: number } & CBatch
}

/**
 * What a beforeBatch pipeline produces. Hooks may enrich elements (values or
 * contexts) and the batch context, but must return exactly as many elements as
 * they received — batch completion tracking counts messages, so a changed
 * element count is a contract violation and the feed is rejected.
 */
export interface BeforeBatchOutput<TInput, CInput, CBatch> {
    elements: OkResultWithContext<TInput, CInput>[]
    batchContext: CBatch & { batchId: number }
}

export interface AfterBatchInput<TOutput, COutput, CBatch, R extends string = never> {
    elements: BatchPipelineResultWithContext<TOutput, COutput, R>
    batchContext: CBatch
    batchId: number
}

/**
 * What an afterBatch pipeline produces. Structurally the same as
 * `AfterBatchInput` — extending it means a passthrough step (one that
 * returns its input untouched) satisfies the afterBatch contract without
 * needing an explicit Input→Output transformer in front. The runtime
 * downstream of `afterPipeline.process(...)` only reads `elements`, so
 * carrying `batchId` through is harmless.
 */
export interface AfterBatchOutput<TOutput, COutput, CBatch, R extends string = never>
    extends AfterBatchInput<TOutput, COutput, CBatch, R> {}

export type BeforeBatchStep<TInput, CInput, CBatchInput, CBatchOutput = CBatchInput> = (
    input: BeforeBatchInput<TInput, CInput, CBatchInput>
) => Promise<PipelineResult<BeforeBatchOutput<TInput, CInput, CBatchOutput>>>

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
    batchContext: CBatch & { batchId: number }
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
 * - feed() with zero elements is a no-op that returns ok — no batch is
 *   registered and no hooks run (a zero-message batch could never complete).
 * - feed() runs beforeBatch which returns enriched elements (same count as
 *   fed — count changes are rejected) and side effects. Elements are tagged
 *   with messageId, then fed to the sub-pipeline.
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
    CBatchOutput,
    COutput extends BatchingContext,
    R extends string = never,
> {
    private nextBatchId = 0
    private nextMessageId = 0
    // Incremented in the same synchronous block that registers a batch and
    // pushes its elements into the sub-pipeline; lets the pump tell a feed that
    // raced its pull apart from genuinely vanished messages.
    private feedEpoch = 0
    private batches = new Map<number, TrackedBatch<TOutput, CBatchOutput, COutput, R>>()
    private messageIdToBatchId = new Map<number, number>()
    private completedResults: BatchResult<BatchPipelineResultWithContext<TOutput, COutput, R>>[] = []

    // With concurrentBatches > 1, callers (e.g. HTTP request handlers in the
    // ingestion API server) invoke feed()/next() concurrently, but the
    // sub-pipeline stages are not safe for concurrent callers: a caller can
    // pull elements upstream and, while awaiting a processing step, leave the
    // pipeline looking "empty" to a concurrent caller — which then observes a
    // spurious null (treated as a fatal drain inconsistency) or routes a later
    // batch's elements ahead of an earlier one (per-key ordering violation).
    // These FIFO mutexes serialize the cheap pull/route/bookkeeping sections;
    // event processing inside the sub-pipeline stays fully concurrent.
    private feedLimit = pLimit(1)
    private pumpLimit = pLimit(1)

    private options: BatchingPipelineOptions

    constructor(
        private subPipeline: BatchPipeline<
            TInput & CBatchOutput & { batchId: number },
            TOutput,
            CInput & BatchingContext,
            COutput,
            R
        >,
        private beforePipeline: Pipeline<
            BeforeBatchInput<TInput, CInput>,
            BeforeBatchOutput<TInput, CInput, CBatchOutput>,
            Record<string, never>
        >,
        private afterPipeline: Pipeline<
            AfterBatchInput<TOutput, COutput, CBatchOutput, R>,
            AfterBatchOutput<TOutput, COutput, CBatchOutput, R>,
            Record<string, never>
        >,
        options?: Partial<BatchingPipelineOptions>
    ) {
        this.options = { ...BATCHING_PIPELINE_DEFAULTS, ...options }
    }

    feed(elements: OkResultWithContext<TInput, CInput>[]): Promise<FeedResult> {
        // Serialize so buffer order always matches batchId order: without this,
        // the await on beforePipeline between batchId assignment and
        // subPipeline.feed() lets two concurrent feeds enter the buffer inverted.
        // With one concurrent batch the caller is already sequential, so the
        // mutex is uncontended.
        return this.feedLimit(() => this.feedSerialized(elements))
    }

    private async feedSerialized(elements: OkResultWithContext<TInput, CInput>[]): Promise<FeedResult> {
        // An empty feed has no messages that could ever complete a batch:
        // completion is only detected in pump()'s result loop, so registering a
        // zero-message batch would occupy a concurrentBatches slot forever and
        // trip the "null with N in-flight batches" corruption guard on the next
        // pull. Skip it entirely — no batchId consumed, no hooks run, nothing
        // registered — so there are no side effects to surface either.
        if (elements.length === 0) {
            return { ok: true }
        }

        if (this.batches.size >= this.options.concurrentBatches) {
            return {
                ok: false,
                kind: 'at_capacity',
                reason: `at concurrent batch capacity (${this.options.concurrentBatches})`,
            }
        }

        const batchId = this.nextBatchId++

        const beforeInput: BeforeBatchInput<TInput, CInput> = { elements, batchContext: { batchId } }
        const beforeResult = await this.beforePipeline.process(createOkContext(beforeInput, {}))

        if (!isOkResult(beforeResult.result)) {
            return {
                ok: false,
                kind: 'before_batch_failed',
                reason: `beforeBatch hook returned non-ok result for batch ${batchId}`,
            }
        }

        const { elements: mappedElements, batchContext } = beforeResult.result.value
        const beforeSideEffects = beforeResult.context.sideEffects

        // beforeBatch may enrich elements and batch context but must not change
        // the element count: a shrunken batch (worst case zero elements) could
        // never complete and would leak its concurrentBatches slot forever. A
        // count change is a contract violation, so reject the feed loudly.
        if (mappedElements.length !== elements.length) {
            return {
                ok: false,
                kind: 'before_batch_failed',
                reason: `beforeBatch changed element count (${elements.length} -> ${mappedElements.length}) for batch ${batchId}`,
            }
        }

        const messageIds: number[] = []
        const inflight = new Set<number>()

        const taggedElements = mappedElements.map((element) => {
            const messageId = this.nextMessageId++
            messageIds.push(messageId)
            inflight.add(messageId)
            this.messageIdToBatchId.set(messageId, batchId)

            return {
                result: {
                    ...element.result,
                    value: {
                        ...element.result.value,
                        ...batchContext,
                    },
                },
                context: {
                    ...element.context,
                    messageId,
                },
            }
        })

        // Registration and the buffer push happen in one synchronous block, and
        // feedEpoch records that it happened — the pump uses it to distinguish
        // "a feed landed during my pull" from genuinely lost messages.
        this.batches.set(batchId, {
            batchContext,
            messageIds,
            inflight,
            results: new Map(),
            beforeSideEffects,
        })
        this.feedEpoch++

        this.subPipeline.feed(taggedElements)
        return { ok: true }
    }

    next(): Promise<BatchResult<BatchPipelineResultWithContext<TOutput, COutput, R>> | null> {
        // Serialize so exactly one caller pumps the sub-pipeline at a time,
        // restoring the single-caller assumption the stages were written under.
        // With one concurrent batch the caller is already sequential, so the
        // mutex is uncontended. Group processing started by the pump runs
        // concurrently in the background regardless of who holds the pump.
        return this.pumpLimit(() => this.pump())
    }

    private async pump(): Promise<BatchResult<BatchPipelineResultWithContext<TOutput, COutput, R>> | null> {
        // Re-check after acquiring the pump: a previous pump iteration may have
        // completed additional batches while this caller was waiting.
        if (this.completedResults.length > 0) {
            return this.completedResults.shift()!
        }

        while (true) {
            const feedEpochAtPullStart = this.feedEpoch
            const result = await this.subPipeline.next()
            if (result === null) {
                if (this.batches.size > 0) {
                    // A feed can land while this pull is resolving null from an
                    // empty pipeline: the new batch gets registered and its
                    // elements buffered, but the pull already made its
                    // emptiness decision. A changed feedEpoch proves that's
                    // what happened — retry the pull, which now picks up the
                    // buffered elements. An unchanged feedEpoch means in-flight
                    // messages genuinely vanished, which is the corruption this
                    // guard exists for.
                    if (this.feedEpoch !== feedEpochAtPullStart) {
                        continue
                    }
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

                    const afterInput: AfterBatchInput<TOutput, COutput, CBatchOutput, R> = {
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
