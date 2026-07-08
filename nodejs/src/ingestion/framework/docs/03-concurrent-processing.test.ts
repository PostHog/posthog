/**
 * # Chapter 3: Concurrent Processing
 *
 * The `concurrently()` method processes items in parallel, improving
 * throughput for I/O-bound operations. Concurrency is unbounded by default -
 * every item in a batch starts processing at the same time. Pass
 * `{ maxConcurrency }` to cap how many items run at once. Although items are
 * processed concurrently, results are returned in the original input order,
 * one item at a time as they complete.
 *
 * ## When to Use Concurrent Processing
 *
 * - External API calls where each item is independent
 * - File operations that don't depend on each other
 * - Any I/O-bound work where parallelism helps
 *
 * ## Tradeoffs
 *
 * - **Throughput**: Higher with concurrency
 * - **Order**: Results maintain input order (but returned one by one)
 * - **Resources**: More concurrent connections/requests (unbounded by
 *   default; bound with `maxConcurrency`)
 *
 * ## Bounding Concurrency
 *
 * ```
 * .concurrently(callback, { maxConcurrency: 2 })
 * ```
 *
 * Unbounded concurrency is simplest but can overwhelm a downstream
 * dependency (a database, an external API with a connection limit). A cap
 * keeps at most N items in flight, starting the next item only as a slot
 * frees up. Emission order stays FIFO regardless of the cap.
 */
import { newBatchPipelineBuilder, newPipelineBuilder } from '~/ingestion/framework/builders'
import { createOkContext } from '~/ingestion/framework/helpers'
import { isOkResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { consumeAll } from './helpers'

describe('Concurrent Processing', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    /**
     * The concurrently() method processes items in parallel.
     * Each item runs through the inner pipeline independently.
     */
    it('concurrently() processes items in parallel', async () => {
        const processed: number[] = []

        function createSlowStep(): ProcessingStep<number, number> {
            return async function slowStep(n) {
                await new Promise((resolve) => setTimeout(resolve, 100))
                processed.push(n)
                return ok(n * 2)
            }
        }

        const pipeline = newBatchPipelineBuilder<number>()
            .concurrently((builder) => builder.pipe(createSlowStep()))
            .build()

        const batch = [1, 2, 3].map((n) => createOkContext(n, {}))
        pipeline.feed(batch)

        const allValues = await consumeAll(pipeline, 100)

        expect(processed.length).toBe(3)
        expect(allValues).toEqual([2, 4, 6])
    })

    /**
     * Items are returned one by one as they complete processing.
     * Each call to next() returns one item (not the whole batch).
     */
    it('items are returned one by one as they complete', async () => {
        function createSlowStep(): ProcessingStep<number, number> {
            return async function slowStep(n) {
                await new Promise((resolve) => setTimeout(resolve, 10))
                return ok(n * 10)
            }
        }

        const pipeline = newBatchPipelineBuilder<number>()
            .concurrently((builder) => builder.pipe(createSlowStep()))
            .build()

        const batch = [1, 2, 3].map((n) => createOkContext(n, {}))
        pipeline.feed(batch)

        // Collect batches as they arrive
        const batches: number[][] = []
        const collectResults = (async () => {
            let result = await pipeline.next()
            while (result !== null) {
                batches.push(
                    result.filter((r) => isOkResult(r.result)).map((r) => (r.result as { value: number }).value)
                )
                result = await pipeline.next()
            }
        })()

        // Concurrent: all items complete after 10ms
        await jest.advanceTimersByTimeAsync(10)
        await collectResults

        // Each call to next() returned exactly 1 item
        expect(batches).toEqual([[10], [20], [30]])
    })

    /**
     * Result ordering matches input order, even when steps complete
     * in a different order.
     */
    it('result ordering matches input order', async () => {
        const completionOrder: number[] = []

        function createVariableDelayStep(): ProcessingStep<number, number> {
            return async function variableDelayStep(n) {
                // Items complete in reverse order: 3 finishes first, then 2, then 1
                const delay = (4 - n) * 10
                await new Promise((resolve) => setTimeout(resolve, delay))
                completionOrder.push(n)
                return ok(n * 10)
            }
        }

        const pipeline = newBatchPipelineBuilder<number>()
            .concurrently((builder) => builder.pipe(createVariableDelayStep()))
            .build()

        const batch = [1, 2, 3].map((n) => createOkContext(n, {}))
        pipeline.feed(batch)

        const allValues = await consumeAll(pipeline, 30)

        // Steps completed in reverse order (3, 2, 1)
        expect(completionOrder).toEqual([3, 2, 1])

        // But results maintain input order (1, 2, 3 -> 10, 20, 30)
        expect(allValues).toEqual([10, 20, 30])
    })

    /**
     * `{ maxConcurrency }` caps how many items process at once. With 5 items,
     * a delay of 100ms each, and a cap of 2, work proceeds in waves of 2, 2, 1:
     * the third item can only start once one of the first two frees its slot.
     *
     * ```
     * Time ──────────────────────────────────────────►
     *  cap=2   [1]──►100ms     [3]──►100ms     [5]──►100ms
     *          [2]──►100ms     [4]──►100ms
     * ```
     *
     * The peak number of items running simultaneously never exceeds the cap.
     */
    it('maxConcurrency caps how many items run at once', async () => {
        let running = 0
        let peak = 0

        function createTrackingStep(): ProcessingStep<number, number> {
            return async function trackingStep(n) {
                running++
                peak = Math.max(peak, running)
                await new Promise((resolve) => setTimeout(resolve, 100))
                running--
                return ok(n * 2)
            }
        }

        const pipeline = newBatchPipelineBuilder<number>()
            .concurrently((builder) => builder.pipe(createTrackingStep()), { maxConcurrency: 2 })
            .build()

        const batch = [1, 2, 3, 4, 5].map((n) => createOkContext(n, {}))
        pipeline.feed(batch)

        // Three waves of 100ms (2 + 2 + 1 items)
        const allValues = await consumeAll(pipeline, 300)

        // Reached the cap (proving parallelism) but never exceeded it
        expect(peak).toBe(2)
        // Results still stream out in input order
        expect(allValues).toEqual([2, 4, 6, 8, 10])
    })

    /**
     * `pipeConcurrently()` is the same as `concurrently()` but takes an
     * already-built `Pipeline` instead of a builder callback. Use it when the
     * per-item pipeline is constructed elsewhere (e.g. shared across pipelines
     * or built by a factory) and you want to plug it in directly.
     *
     * It accepts the same `{ maxConcurrency }` option.
     */
    it('pipeConcurrently() runs a pre-built pipeline per item', async () => {
        function createDoubleStep(): ProcessingStep<number, number> {
            return async function doubleStep(n) {
                await new Promise((resolve) => setTimeout(resolve, 10))
                return ok(n * 2)
            }
        }

        // The per-item pipeline is built up front, then handed to pipeConcurrently
        const perItemPipeline = newPipelineBuilder<number>().pipe(createDoubleStep()).build()

        const pipeline = newBatchPipelineBuilder<number>().pipeConcurrently(perItemPipeline).build()

        const batch = [1, 2, 3].map((n) => createOkContext(n, {}))
        pipeline.feed(batch)

        const allValues = await consumeAll(pipeline, 10)

        expect(allValues).toEqual([2, 4, 6])
    })
})
