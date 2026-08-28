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
 *
 * ## Chunks vs batches
 *
 * These two words name different things, and the difference matters as soon as
 * a pipeline regroups its inputs.
 *
 * A **batch** is one `feed()` call's worth of elements:
 * the unit a consumer hands in, such as a Kafka consumer batch or an HTTP
 * request batch.
 * Batches are what `BatchingPipeline` (chapter 14) tracks with `batchId` and
 * its `beforeBatch`/`afterBatch` hooks.
 *
 * A **chunk** is the array of elements a pipeline stage processes at once and
 * passes downstream:
 * what a `ChunkProcessingStep` receives and what `next()` returns.
 *
 * The two are not the same, and their boundaries need not line up.
 * A chunk can hold elements from several batches, and one batch's elements can
 * spread across many chunks.
 * Stages like gather, interleave, and grouping regroup freely, and the
 * buffering start stage concatenates consecutive feeds.
 * The tests under "Chunks vs batches" below show both directions.
 */
import { newChunkPipelineBuilder } from '~/ingestion/framework/builders'
import { createOkContext } from '~/ingestion/framework/helpers'
import { PipelineResult, dlq, isOkResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { collectChunks } from './helpers'

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

describe('Chunks vs batches', () => {
    /**
     * A chunk can span multiple batches. Each feed() is one batch, but the
     * buffering start stage concatenates consecutive feeds, so two feed() calls
     * that happen before a single next() come out as one chunk. The chunk step
     * is called once, with every element from both batches.
     */
    it('two batches emerge as a single chunk', async () => {
        const chunkLengths: number[] = []

        function createRecordingStep(): ChunkProcessingStep<number, number> {
            return function recordingStep(items) {
                chunkLengths.push(items.length)
                return Promise.resolve(items.map((n) => ok(n)))
            }
        }

        const pipeline = newChunkPipelineBuilder<number>().pipeChunk(createRecordingStep()).build()

        // Two separate feed() calls are two batches
        pipeline.feed([1, 2].map((n) => createOkContext(n, {})))
        pipeline.feed([3, 4, 5].map((n) => createOkContext(n, {})))

        // A single next() pulls both batches out together
        const results = await pipeline.next()

        expect(results!.length).toBe(5)
        // The step saw one chunk of 5, spanning both batches (2 + 3)
        expect(chunkLengths).toEqual([5])
    })

    /**
     * The reverse also holds: one batch can spread across many chunks. A single
     * feed() of events across two groups is regrouped by concurrentlyPerGroup,
     * which emits one chunk per group as it completes. The one batch comes out
     * as two chunks, not one.
     */
    it('one batch spreads across multiple chunks', async () => {
        interface Event {
            userId: string
            eventId: number
        }

        function createIdentityStep(): ProcessingStep<Event, Event> {
            return function identityStep(event) {
                return Promise.resolve(ok(event))
            }
        }

        const pipeline = newChunkPipelineBuilder<Event>()
            .concurrentlyPerGroup(
                (event) => event.userId,
                (group) => group.sequentially((groupBuilder) => groupBuilder.pipe(createIdentityStep()))
            )
            .build()

        // One feed() call is one batch: four events across two groups
        const events: Event[] = [
            { userId: 'alice', eventId: 1 },
            { userId: 'bob', eventId: 2 },
            { userId: 'alice', eventId: 3 },
            { userId: 'bob', eventId: 4 },
        ]
        pipeline.feed(events.map((e) => createOkContext(e, {})))

        const chunks = await collectChunks(pipeline)

        // The single batch came out as two chunks, one per group
        expect(chunks.length).toBe(2)
        expect(chunks.map((chunk) => chunk.length)).toEqual([2, 2])
    })
})
