/**
 * # Chapter 14: Batching Pipelines
 *
 * `newBatchingPipeline(beforeBatch, callback, afterBatch, options?)` builds a
 * `BatchingPipeline` that runs a hook before a batch enters the sub-pipeline
 * and another after every item in that batch has come out. It is the tool for
 * per-batch setup/teardown: prefetching data all the items in a batch will
 * need, or flushing an accumulated write once the batch is done.
 *
 * ## Key concepts
 *
 * - **A batch is one `feed()` call.** The batching pipeline does not accumulate
 *   items itself - the caller decides batch boundaries (by size, by time, by
 *   however it chooses) and each `feed()` becomes exactly one batch.
 * - **`beforeBatch`** runs once per batch before its items enter the
 *   sub-pipeline. It receives the batch's elements and a `batchContext`, and
 *   can enrich both (e.g. attach a shared store) for the whole batch.
 *   Enrich only: it must return exactly the elements it received (same
 *   count). Filtering belongs in sub-pipeline steps that return `drop()`
 *   results - a count-changing hook throws (see below).
 * - **`callback`** builds the per-item sub-pipeline (the same builder DSL as
 *   the other chapters).
 * - **`afterBatch`** runs once per batch after all its items exit, receiving
 *   the ordered results plus the `batchContext` and `batchId`.
 * - **`batchId`** is a monotonic id assigned per batch; each element is also
 *   tagged with a monotonic `messageId` in its context.
 *
 * ## How it works
 *
 * ```
 * feed(batch A) ─► beforeBatch(A) ─► [ sub-pipeline ] ─► afterBatch(A) ─► next()
 * feed(batch B) ─► beforeBatch(B) ─► [ sub-pipeline ] ─► afterBatch(B) ─► next()
 * ```
 *
 * Unlike a plain `BatchPipeline`, `feed()` is async and returns a `FeedResult`:
 * `{ ok: true }` when accepted, or `{ ok: false, kind, reason }` when rejected.
 * `next()` returns a `BatchResult` (`{ elements, sideEffects }`) per completed
 * batch, or `null` when fully drained. Batches are returned in completion
 * order; items within a batch keep their feed order.
 *
 * ## Backpressure
 *
 * `concurrentBatches` (default 1) caps how many batches can be in flight at
 * once. When the pipeline is at capacity, `feed()` returns
 * `{ ok: false, kind: 'at_capacity' }` instead of accepting the batch -
 * the caller must drain a batch (via `next()`) to free a slot before retrying.
 *
 * ## The lifecycle hooks contract
 *
 * Batch completion is tracked by counting messages, so a batch's element
 * count is load-bearing:
 *
 * - **An empty `feed()` is a no-op.** It returns `{ ok: true }` without
 *   running hooks, consuming a batchId, or occupying a capacity slot - a
 *   zero-message batch could never complete.
 * - **`beforeBatch` must preserve the element count.** A hook that returns
 *   fewer (or more) elements than it received breaks completion tracking:
 *   the batch could never complete and would leak its capacity slot. That is
 *   a logic error in the hook, so `feed()` throws rather than returning a
 *   `FeedResult`. To discard items, use sub-pipeline steps that return
 *   `drop()` results (chapter 7) - dropped items still count as completed.
 */
import { newBatchingPipeline } from '~/ingestion/framework/builders'
import { createOkContext } from '~/ingestion/framework/helpers'
import { isOkResult, ok } from '~/ingestion/framework/results'

interface Event {
    id: number
}

type NoCtx = Record<string, never>

describe('Batching Pipelines', () => {
    /**
     * Each feed() call is one batch: beforeBatch and afterBatch fire once per
     * batch, batchIds increment, and every element is tagged with a monotonic
     * messageId that continues across batches.
     */
    it('each feed() forms one batch with sequential batchId and messageId tagging', async () => {
        const beforeBatchIds: number[] = []
        const afterBatchIds: number[] = []

        const pipeline = newBatchingPipeline<Event, Event, NoCtx>(
            (builder) =>
                builder.pipe(function recordingBefore(input) {
                    beforeBatchIds.push(input.batchContext.batchId)
                    return Promise.resolve(ok({ elements: input.elements, batchContext: input.batchContext }))
                }),
            (builder) => builder,
            (builder) =>
                builder.pipe(function recordingAfter(input) {
                    afterBatchIds.push(input.batchId)
                    return Promise.resolve(ok(input))
                }),
            { concurrentBatches: Infinity }
        )

        await pipeline.feed([{ id: 10 }, { id: 20 }].map((e) => createOkContext(e, {})))
        await pipeline.feed([{ id: 30 }].map((e) => createOkContext(e, {})))

        const messageIds: number[] = []
        let batch = await pipeline.next()
        while (batch !== null) {
            for (const element of batch.elements) {
                messageIds.push(element.context.messageId)
            }
            batch = await pipeline.next()
        }

        // One beforeBatch/afterBatch per feed(), batchIds increment
        expect(beforeBatchIds).toEqual([0, 1])
        expect(afterBatchIds).toEqual([0, 1])
        // messageIds are monotonic and continue across batches
        expect(messageIds).toEqual([0, 1, 2])
    })

    /**
     * beforeBatch can attach a shared store to the batchContext; that same
     * context is handed to afterBatch. This is how a batch prefetches data once
     * and cleans up once, rather than per item.
     */
    it('batch context flows from beforeBatch to afterBatch', async () => {
        type BatchStore = { store: string }
        let seenInAfter: string | undefined

        const pipeline = newBatchingPipeline<Event, Event, NoCtx, BatchStore>(
            (builder) =>
                builder.pipe(function attachStore(input) {
                    return Promise.resolve(
                        ok({
                            elements: input.elements,
                            batchContext: { ...input.batchContext, store: `store-${input.batchContext.batchId}` },
                        })
                    )
                }),
            (builder) => builder,
            (builder) =>
                builder.pipe(function readStore(input) {
                    seenInAfter = input.batchContext.store
                    return Promise.resolve(ok(input))
                }),
            { concurrentBatches: Infinity }
        )

        await pipeline.feed([{ id: 1 }].map((e) => createOkContext(e, {})))
        await pipeline.next()

        expect(seenInAfter).toBe('store-0')
    })

    /**
     * `concurrentBatches` caps how many batches are in flight. At the default
     * of 1, a second feed() before the first drains is rejected with an
     * `at_capacity` FeedResult. Draining a batch frees the slot.
     */
    it('feed() reports at_capacity backpressure when concurrentBatches is exceeded', async () => {
        const pipeline = newBatchingPipeline<Event, Event, NoCtx>(
            (builder) =>
                builder.pipe(function passThroughBefore(input) {
                    return Promise.resolve(ok({ elements: input.elements, batchContext: input.batchContext }))
                }),
            (builder) => builder,
            (builder) =>
                builder.pipe(function passThroughAfter(input) {
                    return Promise.resolve(ok(input))
                }),
            { concurrentBatches: 1 }
        )

        // First batch accepted
        expect(await pipeline.feed([{ id: 1 }].map((e) => createOkContext(e, {})))).toEqual({ ok: true })

        // Second batch rejected: already at capacity
        const rejected = await pipeline.feed([{ id: 2 }].map((e) => createOkContext(e, {})))
        expect(rejected).toMatchObject({ ok: false, kind: 'at_capacity' })

        // Draining the in-flight batch frees the slot
        const drained = await pipeline.next()
        expect(drained).not.toBeNull()
        expect(drained!.elements.every((e) => isOkResult(e.result))).toBe(true)

        // Now a new batch is accepted again
        expect(await pipeline.feed([{ id: 3 }].map((e) => createOkContext(e, {})))).toEqual({ ok: true })
    })

    /**
     * An empty feed() is a no-op: it is accepted, but no batch exists - hooks
     * do not run, no batchId or capacity slot is consumed, and next() has
     * nothing to return.
     */
    it('an empty feed() is a no-op that runs no hooks and consumes no capacity', async () => {
        let beforeBatchRan = false

        const pipeline = newBatchingPipeline<Event, Event, NoCtx>(
            (builder) =>
                builder.pipe(function recordingBefore(input) {
                    beforeBatchRan = true
                    return Promise.resolve(ok({ elements: input.elements, batchContext: input.batchContext }))
                }),
            (builder) => builder,
            (builder) =>
                builder.pipe(function passThroughAfter(input) {
                    return Promise.resolve(ok(input))
                }),
            { concurrentBatches: 1 }
        )

        expect(await pipeline.feed([])).toEqual({ ok: true })
        expect(beforeBatchRan).toBe(false)
        expect(await pipeline.next()).toBeNull()

        // No capacity was consumed: a real batch still fits in the single slot
        expect(await pipeline.feed([{ id: 1 }].map((e) => createOkContext(e, {})))).toEqual({ ok: true })
        expect(await pipeline.next()).not.toBeNull()
    })

    /**
     * beforeBatch is enrich-only: it must return exactly the elements it
     * received. Returning a different count is a logic error - feed() throws.
     * To discard items, use sub-pipeline steps that return drop() results
     * instead; dropped items still count toward batch completion.
     */
    it('a beforeBatch that changes the element count throws', async () => {
        const pipeline = newBatchingPipeline<Event, Event, NoCtx>(
            (builder) =>
                builder.pipe(function filteringBefore(input) {
                    // Wrong: hooks must not filter elements
                    return Promise.resolve(ok({ elements: input.elements.slice(1), batchContext: input.batchContext }))
                }),
            (builder) => builder,
            (builder) =>
                builder.pipe(function passThroughAfter(input) {
                    return Promise.resolve(ok(input))
                }),
            { concurrentBatches: 1 }
        )

        await expect(pipeline.feed([{ id: 1 }, { id: 2 }].map((e) => createOkContext(e, {})))).rejects.toThrow(
            'changed element count (2 -> 1)'
        )
    })
})
