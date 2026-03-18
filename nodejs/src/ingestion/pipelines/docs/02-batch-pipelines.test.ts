/**
 * # Chapter 2: Batch Pipelines
 *
 * Batch pipelines process multiple items at once, which is more efficient
 * for I/O-bound operations like database queries or API calls. Instead of
 * N individual calls, you make one batched call.
 *
 * ## Key Concepts
 *
 * - **feed/next interface**: Feed batches in, pull results out
 * - **Cardinality guarantee**: Batch steps must return same number of results as inputs
 * - **OK filtering**: Non-OK items are automatically filtered before batch steps
 *
 * ## When to Use Batch Pipelines
 *
 * - Database lookups (batch SELECT)
 * - External API calls with batch endpoints
 * - Bulk writes (batch INSERT)
 */
import { newBatchPipelineBuilder } from '../builders'
import { createContext } from '../helpers'
import { PipelineResult, dlq, isOkResult, ok } from '../results'

/**
 * Type for batch processing steps - takes an array of values and returns
 * an array of results (must have same length).
 */
type BatchProcessingStep<T, U> = (values: T[]) => Promise<PipelineResult<U>[]>

describe('Batch Pipeline Basics', () => {
    /**
     * Batch pipelines process multiple items in a single step call.
     * This is more efficient than processing items one at a time.
     */
    it('batch pipelines process multiple items at once', async () => {
        let callCount = 0

        function createBatchDoubleStep(): BatchProcessingStep<number, number> {
            return function batchDoubleStep(items) {
                callCount++
                return Promise.resolve(items.map((n) => ok(n * 2)))
            }
        }

        const pipeline = newBatchPipelineBuilder<number>().pipeBatch(createBatchDoubleStep()).build()

        const batch = [1, 2, 3, 4, 5].map((n) => createContext(ok(n)))
        pipeline.feed(batch)

        const results = await pipeline.next()

        // Step was called once with all 5 items (not 5 times)
        expect(callCount).toBe(1)
        expect(results!.map((r) => (isOkResult(r.result) ? r.result.value : null))).toEqual([2, 4, 6, 8, 10])
    })

    /**
     * The feed() method accepts a batch of items to process.
     * The next() method returns processed results. When all items are
     * processed, next() returns null.
     */
    it('feed() accepts items and next() returns results then null', async () => {
        function createUppercaseStep(): BatchProcessingStep<string, string> {
            return function uppercaseStep(items) {
                return Promise.resolve(items.map((s) => ok(s.toUpperCase())))
            }
        }

        const pipeline = newBatchPipelineBuilder<string>().pipeBatch(createUppercaseStep()).build()

        const batch = ['a', 'b', 'c'].map((s) => createContext(ok(s)))
        pipeline.feed(batch)

        const results = await pipeline.next()
        expect(results).not.toBeNull()
        expect(results!.map((r) => (isOkResult(r.result) ? r.result.value : null))).toEqual(['A', 'B', 'C'])

        const noMore = await pipeline.next()
        expect(noMore).toBeNull()
    })
})

describe('Cardinality Guarantee', () => {
    /**
     * Batch steps must return the same number of results as inputs.
     * This ensures each input has a corresponding output.
     */
    it('batch steps must return same number of results as inputs', async () => {
        function createValidBatchStep(): BatchProcessingStep<number, number> {
            return function validBatchStep(items) {
                return Promise.resolve(items.map((n) => ok(n * 2)))
            }
        }

        const pipeline = newBatchPipelineBuilder<number>().pipeBatch(createValidBatchStep()).build()

        const batch = [1, 2, 3].map((n) => createContext(ok(n)))
        pipeline.feed(batch)

        const results = await pipeline.next()

        expect(results).not.toBeNull()
        expect(results!.length).toBe(3)
    })

    /**
     * If a batch step returns a different number of results than inputs,
     * the pipeline throws an error.
     */
    it('mismatched result count throws an error', async () => {
        function createBadBatchStep(): BatchProcessingStep<number, number> {
            return function badBatchStep(items) {
                // Returns wrong length - invalid!
                return Promise.resolve([ok(items[0])])
            }
        }

        const pipeline = newBatchPipelineBuilder<number>().pipeBatch(createBadBatchStep()).build()

        const batch = [1, 2, 3].map((n) => createContext(ok(n)))
        pipeline.feed(batch)

        await expect(pipeline.next()).rejects.toThrow(/different number of results than input values/)
    })
})

describe('OK Filtering', () => {
    /**
     * Batch steps only receive OK items. Non-OK items (DLQ, DROP, REDIRECT)
     * are automatically filtered out and preserved in the output.
     */
    it('batch steps receive only OK items from previous steps', async () => {
        const receivedInSecondStep: number[] = []

        function createFilterStep(): BatchProcessingStep<number, number> {
            return function filterStep(items) {
                return Promise.resolve(
                    items.map((n) => {
                        if (n > 3) {
                            return dlq(`Number ${n} is too large`)
                        }
                        return ok(n)
                    })
                )
            }
        }

        function createProcessStep(): BatchProcessingStep<number, number> {
            return function processStep(items) {
                receivedInSecondStep.push(...items)
                return Promise.resolve(items.map((n) => ok(n * 10)))
            }
        }

        const pipeline = newBatchPipelineBuilder<number>()
            .pipeBatch(createFilterStep())
            .pipeBatch(createProcessStep())
            .build()

        const batch = [1, 2, 3, 4, 5].map((n) => createContext(ok(n)))
        pipeline.feed(batch)

        await pipeline.next()

        // Second step only received items 1, 2, 3 (4 and 5 were DLQed)
        expect(receivedInSecondStep).toEqual([1, 2, 3])
    })
})
