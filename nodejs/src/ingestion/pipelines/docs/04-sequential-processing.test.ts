/**
 * # Chapter 4: Sequential Processing
 *
 * The `sequentially()` method processes items one at a time, preserving order.
 * Use it when order matters or when you need to limit concurrent operations.
 * Unlike concurrent processing which returns items one by one as they complete,
 * sequential processing returns all items together in a single batch after
 * all processing is done.
 *
 * ## When to Use Sequential Processing
 *
 * - Operations that must happen in order (e.g., database transactions)
 * - Rate-limited APIs where you can't make parallel requests
 * - When you need predictable resource usage
 *
 * ## Tradeoffs
 *
 * - **Order**: Strictly preserved
 * - **Throughput**: Lower than concurrent (one at a time)
 * - **Resources**: Minimal concurrent connections
 * - **Batching**: Results returned together (not streamed)
 */
import { newBatchPipelineBuilder } from '../builders'
import { createContext } from '../helpers'
import { isOkResult, ok } from '../results'
import { ProcessingStep } from '../steps'
import { consumeAll } from './helpers'

describe('Sequential Processing', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    /**
     * The sequentially() method processes items one at a time.
     * Each item waits for the previous one to complete.
     */
    it('sequentially() processes items one at a time', async () => {
        const processingOrder: number[] = []

        function createOrderTrackingStep(): ProcessingStep<number, number> {
            return async function orderTrackingStep(n) {
                await new Promise((resolve) => setTimeout(resolve, 10))
                processingOrder.push(n)
                return ok(n)
            }
        }

        const pipeline = newBatchPipelineBuilder<number>()
            .sequentially((builder) => builder.pipe(createOrderTrackingStep()))
            .build()

        const batch = [1, 2, 3].map((n) => createContext(ok(n)))
        pipeline.feed(batch)

        // Sequential: need to advance time for each item (3 items x 10ms = 30ms)
        const allValues = await consumeAll(pipeline, 30)

        // Items processed in order
        expect(processingOrder).toEqual([1, 2, 3])
        // Results also in order
        expect(allValues).toEqual([1, 2, 3])
    })

    /**
     * Unlike concurrent processing, sequential returns all items in one batch
     * after processing them one at a time.
     */
    it('all items are returned together after sequential processing', async () => {
        function createSlowStep(): ProcessingStep<number, number> {
            return async function slowStep(n) {
                await new Promise((resolve) => setTimeout(resolve, 10))
                return ok(n * 10)
            }
        }

        const pipeline = newBatchPipelineBuilder<number>()
            .sequentially((builder) => builder.pipe(createSlowStep()))
            .build()

        const batch = [1, 2, 3].map((n) => createContext(ok(n)))
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

        // Sequential: need 30ms total (10ms per item)
        await jest.advanceTimersByTimeAsync(30)
        await collectResults

        // All items returned in a single batch (unlike concurrent which returns 1 at a time)
        expect(batches).toEqual([[10, 20, 30]])
    })

    /**
     * Result ordering always matches input order with sequential processing.
     */
    it('result ordering matches input order', async () => {
        const completionOrder: number[] = []

        function createTrackingStep(): ProcessingStep<number, number> {
            return async function trackingStep(n) {
                await new Promise((resolve) => setTimeout(resolve, 10))
                completionOrder.push(n)
                return ok(n * 10)
            }
        }

        const pipeline = newBatchPipelineBuilder<number>()
            .sequentially((builder) => builder.pipe(createTrackingStep()))
            .build()

        const batch = [3, 1, 2].map((n) => createContext(ok(n)))
        pipeline.feed(batch)

        const allValues = await consumeAll(pipeline, 30)

        // Items processed in input order (3, 1, 2)
        expect(completionOrder).toEqual([3, 1, 2])

        // Results also in input order (3, 1, 2 -> 30, 10, 20)
        expect(allValues).toEqual([30, 10, 20])
    })
})
