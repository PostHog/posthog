/**
 * # Chapter 15: Consuming a Pipeline
 *
 * The earlier chapters build pipelines; this one shows how a built
 * `ChunkPipeline` is actually driven in production, and how
 * `BatchPipelineUnwrapper` turns its results into plain values.
 *
 * ## The feed() / next() contract
 *
 * A `ChunkPipeline` is a pull-based stream:
 *
 * - **`feed(elements)`** hands a batch of `OkResultWithContext` items to the
 *   pipeline. It buffers them; it does not process synchronously.
 * - **`next()`** pulls the next available chunk of results (each a
 *   result-with-context), driving processing as needed. Depending on the
 *   stages involved, a `next()` may return one item, one group, or a whole
 *   batch.
 * - **`next()` returns `null` when the pipeline is drained** - everything fed
 *   has been processed and emitted. A consumer loops `next()` until it sees
 *   `null`, then feeds the next batch.
 *
 * ```
 * pipeline.feed(batch)
 * let results = await pipeline.next()
 * while (results !== null) {
 *   // handle results
 *   results = await pipeline.next()
 * }
 * ```
 *
 * ## BatchPipelineUnwrapper
 *
 * Most consumers do not want result-with-context objects; they want the plain
 * output values. `BatchPipelineUnwrapper` wraps a pipeline and, on `next()`,
 * returns a flat `TOutput[]` of just the OK values - non-OK results (DLQ, DROP,
 * REDIRECT) are filtered out (they are assumed already handled by a
 * `handleResults()` stage upstream). It returns `null` when the underlying
 * pipeline drains.
 *
 * ### Warning on unhandled side effects
 *
 * The unwrapper is a terminal consumer, so any side effects still attached to
 * the results it sees will never be awaited. When it finds results that still
 * carry side effects, it logs a warning - a signal that a `handleSideEffects()`
 * stage is missing from the pipeline.
 */
import { logger } from '~/common/utils/logger'
import { ChunkProcessingStep } from '~/ingestion/framework/base-chunk-pipeline'
import { BatchPipelineUnwrapper } from '~/ingestion/framework/batch-pipeline-unwrapper'
import { newBatchPipelineBuilder } from '~/ingestion/framework/builders'
import { createOkContext } from '~/ingestion/framework/helpers'
import { drop, isOkResult, ok } from '~/ingestion/framework/results'

interface Event {
    id: number
}

type NoCtx = Record<string, never>

describe('Consuming a Pipeline', () => {
    /**
     * A consumer feeds a batch, then loops next() until it returns null.
     * next() drives processing; null marks the pipeline drained.
     */
    it('feed() then next() drives the pipeline until it returns null', async () => {
        function createDoubleStep(): ChunkProcessingStep<Event, Event> {
            return function doubleStep(events) {
                return Promise.resolve(events.map((event) => ok({ id: event.id * 2 })))
            }
        }

        const pipeline = newBatchPipelineBuilder<Event, NoCtx>().pipeBatch(createDoubleStep()).build()

        pipeline.feed([{ id: 1 }, { id: 2 }, { id: 3 }].map((e) => createOkContext(e, {})))

        const values: number[] = []
        let results = await pipeline.next()
        while (results !== null) {
            for (const r of results) {
                if (isOkResult(r.result)) {
                    values.push(r.result.value.id)
                }
            }
            results = await pipeline.next()
        }

        expect(values).toEqual([2, 4, 6])
        // Once drained, next() keeps returning null
        expect(await pipeline.next()).toBeNull()
    })

    /**
     * BatchPipelineUnwrapper returns plain output values and filters out non-OK
     * results (here, DROP). The consumer never sees result-with-context objects.
     */
    it('BatchPipelineUnwrapper returns plain values and drops non-OK results', async () => {
        function createFilterStep(): ChunkProcessingStep<Event, Event> {
            return function filterStep(events) {
                // Drop even ids, keep odd ones
                return Promise.resolve(events.map((event) => (event.id % 2 === 0 ? drop('even filtered') : ok(event))))
            }
        }

        const pipeline = newBatchPipelineBuilder<Event, NoCtx>().pipeBatch(createFilterStep()).build()
        const unwrapper = new BatchPipelineUnwrapper(pipeline)

        unwrapper.feed([{ id: 1 }, { id: 2 }, { id: 3 }].map((e) => createOkContext(e, {})))

        const values: Event[] = []
        let batch = await unwrapper.next()
        while (batch !== null) {
            values.push(...batch)
            batch = await unwrapper.next()
        }

        // Only the OK (odd) values survive, as plain objects
        expect(values).toEqual([{ id: 1 }, { id: 3 }])
    })

    /**
     * When results still carry side effects (no handleSideEffects() stage ran),
     * the unwrapper logs a warning: those side effects would otherwise be
     * silently dropped.
     */
    it('BatchPipelineUnwrapper warns about unhandled side effects', async () => {
        const warnSpy = jest.spyOn(logger, 'warn').mockImplementation(() => undefined)

        function createStepWithSideEffect(): ChunkProcessingStep<Event, Event> {
            return function stepWithSideEffect(events) {
                // Attach a side effect that no downstream stage handles
                return Promise.resolve(events.map((event) => ok(event, [Promise.resolve('unhandled')])))
            }
        }

        const pipeline = newBatchPipelineBuilder<Event, NoCtx>().pipeBatch(createStepWithSideEffect()).build()
        const unwrapper = new BatchPipelineUnwrapper(pipeline)

        unwrapper.feed([{ id: 1 }].map((e) => createOkContext(e, {})))
        await unwrapper.next()

        expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('remaining side effects'))

        warnSpy.mockRestore()
    })
})
