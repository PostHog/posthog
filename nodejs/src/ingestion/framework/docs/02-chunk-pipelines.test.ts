/**
 * # Chapter 2: Chunk Pipelines
 *
 * Chunk pipelines process multiple items at once, which is more efficient
 * for I/O-bound operations like database queries or API calls. Instead of
 * N individual calls, you make one batched call.
 *
 * ## Key Concepts
 *
 * - **feed/next interface**: Feed batches in, pull results out
 * - **Cardinality guarantee**: Chunk steps must return same number of results as inputs
 * - **OK filtering**: Non-OK items are automatically filtered before chunk steps
 *
 * ## When to Use Chunk Pipelines
 *
 * - Database lookups (batch SELECT)
 * - External API calls with batch endpoints
 * - Bulk writes (batch INSERT)
 */
import { newChunkPipelineBuilder } from '~/ingestion/framework/builders'
import { createOkContext } from '~/ingestion/framework/helpers'
import { PipelineResult, dlq, isOkResult, ok } from '~/ingestion/framework/results'

/**
 * Type for chunk processing steps - takes an array of values and returns
 * an array of results (must have same length).
 */
type ChunkProcessingStep<T, U> = (values: T[]) => Promise<PipelineResult<U>[]>

describe('Chunk Pipeline Basics', () => {
    /**
     * Chunk pipelines process multiple items in a single step call.
     * This is more efficient than processing items one at a time.
     */
    it('chunk pipelines process multiple items at once', async () => {
        let callCount = 0

        function createChunkDoubleStep(): ChunkProcessingStep<number, number> {
            return function chunkDoubleStep(items) {
                callCount++
                return Promise.resolve(items.map((n) => ok(n * 2)))
            }
        }

        const pipeline = newChunkPipelineBuilder<number>().pipeChunk(createChunkDoubleStep()).build()

        const batch = [1, 2, 3, 4, 5].map((n) => createOkContext(n, {}))
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
        function createUppercaseStep(): ChunkProcessingStep<string, string> {
            return function uppercaseStep(items) {
                return Promise.resolve(items.map((s) => ok(s.toUpperCase())))
            }
        }

        const pipeline = newChunkPipelineBuilder<string>().pipeChunk(createUppercaseStep()).build()

        const batch = ['a', 'b', 'c'].map((s) => createOkContext(s, {}))
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
     * Chunk steps must return the same number of results as inputs.
     * This ensures each input has a corresponding output.
     */
    it('chunk steps must return same number of results as inputs', async () => {
        function createValidChunkStep(): ChunkProcessingStep<number, number> {
            return function validChunkStep(items) {
                return Promise.resolve(items.map((n) => ok(n * 2)))
            }
        }

        const pipeline = newChunkPipelineBuilder<number>().pipeChunk(createValidChunkStep()).build()

        const batch = [1, 2, 3].map((n) => createOkContext(n, {}))
        pipeline.feed(batch)

        const results = await pipeline.next()

        expect(results).not.toBeNull()
        expect(results!.length).toBe(3)
    })

    /**
     * If a chunk step returns a different number of results than inputs,
     * the pipeline throws an error.
     */
    it('mismatched result count throws an error', async () => {
        function createBadChunkStep(): ChunkProcessingStep<number, number> {
            return function badChunkStep(items) {
                // Returns wrong length - invalid!
                return Promise.resolve([ok(items[0])])
            }
        }

        const pipeline = newChunkPipelineBuilder<number>().pipeChunk(createBadChunkStep()).build()

        const batch = [1, 2, 3].map((n) => createOkContext(n, {}))
        pipeline.feed(batch)

        await expect(pipeline.next()).rejects.toThrow(/different number of results than input values/)
    })
})

describe('OK Filtering', () => {
    /**
     * Chunk steps only receive OK items. Non-OK items (DLQ, DROP, REDIRECT)
     * are automatically filtered out and preserved in the output.
     */
    it('chunk steps receive only OK items from previous steps', async () => {
        const receivedInSecondStep: number[] = []

        function createFilterStep(): ChunkProcessingStep<number, number> {
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

        function createProcessStep(): ChunkProcessingStep<number, number> {
            return function processStep(items) {
                receivedInSecondStep.push(...items)
                return Promise.resolve(items.map((n) => ok(n * 10)))
            }
        }

        const pipeline = newChunkPipelineBuilder<number>()
            .pipeChunk(createFilterStep())
            .pipeChunk(createProcessStep())
            .build()

        const batch = [1, 2, 3, 4, 5].map((n) => createOkContext(n, {}))
        pipeline.feed(batch)

        await pipeline.next()

        // Second step only received items 1, 2, 3 (4 and 5 were DLQed)
        expect(receivedInSecondStep).toEqual([1, 2, 3])
    })
})
