/**
 * # Chapter 3: Concurrent Processing
 *
 * The `concurrently()` method processes items in parallel, improving
 * throughput for I/O-bound operations. Concurrency is unbounded - all
 * items in a batch start processing at the same time. Although items
 * are processed concurrently, results are returned in the original
 * input order, one item at a time as they complete.
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
 * - **Resources**: More concurrent connections/requests (unbounded)
 */
import { newBatchPipelineBuilder } from '../builders'
import { createContext } from '../helpers'
import { isOkResult, ok } from '../results'
import { ProcessingStep } from '../steps'
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

        const batch = [1, 2, 3].map((n) => createContext(ok(n)))
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

        const batch = [1, 2, 3].map((n) => createContext(ok(n)))
        pipeline.feed(batch)

        const allValues = await consumeAll(pipeline, 30)

        // Steps completed in reverse order (3, 2, 1)
        expect(completionOrder).toEqual([3, 2, 1])

        // But results maintain input order (1, 2, 3 -> 10, 20, 30)
        expect(allValues).toEqual([10, 20, 30])
    })
})
