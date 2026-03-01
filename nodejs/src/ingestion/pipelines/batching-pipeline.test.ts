import { Message } from 'node-rdkafka'

import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { BatchingContext, batch } from './batching-pipeline'
import { newBatchingPipeline } from './builders/helpers'
import { PipelineResultWithContext } from './pipeline.interface'
import { ok } from './results'

type MsgCtx = { message: Message }
type SubCtx = MsgCtx & BatchingContext

function makeMessage(offset: number): Message {
    return {
        topic: 'test-topic',
        partition: 0,
        offset,
        size: 0,
        key: Buffer.from(`key${offset}`),
        value: Buffer.from(`value${offset}`),
        timestamp: Date.now(),
    }
}

function makeBatch(offsets: number[]): BatchPipelineResultWithContext<any, MsgCtx> {
    return offsets.map((offset) => ({
        result: ok({ value: `msg-${offset}` }),
        context: {
            message: makeMessage(offset),
            lastStep: undefined,
            sideEffects: [],
            warnings: [],
        },
    }))
}

describe('BatchingPipeline', () => {
    let beforeBatch: jest.Mock
    let afterBatch: jest.Mock

    beforeEach(() => {
        beforeBatch = jest.fn((elements, _batchId) => batch(elements, {}))
        afterBatch = jest.fn()
    })

    function createCollector(options?: { concurrentBatches?: number }) {
        return newBatchingPipeline<any, any, MsgCtx, Record<string, never>, SubCtx>(
            beforeBatch,
            (builder) => builder,
            afterBatch,
            { concurrentBatches: Infinity, ...options }
        )
    }

    function createStreamingCollector() {
        return newBatchingPipeline<any, any, MsgCtx, Record<string, never>, SubCtx>(
            beforeBatch,
            (builder) => builder.concurrently((b) => b.pipe((value) => Promise.resolve(ok(value)))),
            afterBatch,
            { concurrentBatches: Infinity }
        )
    }

    async function drainAll<C>(pipeline: BatchPipeline<any, any, any, C>) {
        const allResults: PipelineResultWithContext<any, C>[] = []
        let r = await pipeline.next()
        while (r !== null) {
            allResults.push(...r)
            r = await pipeline.next()
        }
        return allResults
    }

    it('returns null when sub-pipeline is empty', async () => {
        const collector = createCollector()
        expect(await collector.next()).toBeNull()
        expect(beforeBatch).not.toHaveBeenCalled()
        expect(afterBatch).not.toHaveBeenCalled()
    })

    it('assigns sequential batch IDs to beforeBatch', () => {
        const collector = createCollector()

        collector.feed(makeBatch([1, 2]))
        collector.feed(makeBatch([3]))

        expect(beforeBatch).toHaveBeenCalledTimes(2)
        expect(beforeBatch.mock.calls[0][1]).toBe(0)
        expect(beforeBatch.mock.calls[0][0]).toHaveLength(2)
        expect(beforeBatch.mock.calls[1][1]).toBe(1)
        expect(beforeBatch.mock.calls[1][0]).toHaveLength(1)
    })

    it('tags each element with a monotonic messageId in context', async () => {
        const collector = createCollector()

        collector.feed(makeBatch([10, 20, 30]))
        const results = await drainAll(collector)

        expect(results).toHaveLength(3)
        expect(results[0].context.messageId).toBe(0)
        expect(results[1].context.messageId).toBe(1)
        expect(results[2].context.messageId).toBe(2)
    })

    it('continues messageId sequence across batches', async () => {
        const collector = createCollector()

        collector.feed(makeBatch([1, 2]))
        collector.feed(makeBatch([3]))
        const results = await drainAll(collector)

        expect(results).toHaveLength(3)
        expect(results[0].context.messageId).toBe(0)
        expect(results[1].context.messageId).toBe(1)
        expect(results[2].context.messageId).toBe(2)
    })

    it('returns ordered batch results when a batch completes', async () => {
        const collector = createCollector()

        collector.feed(makeBatch([1, 2, 3]))
        const results = await drainAll(collector)

        expect(afterBatch).toHaveBeenCalledTimes(1)
        expect(afterBatch.mock.calls[0][1]).toBe(0)
        expect(results).toHaveLength(3)
        expect(results[0].context.messageId).toBe(0)
        expect(results[1].context.messageId).toBe(1)
        expect(results[2].context.messageId).toBe(2)
    })

    it('tracks two batches independently', async () => {
        const collector = createCollector()

        collector.feed(makeBatch([1, 2]))
        collector.feed(makeBatch([3]))
        const results = await drainAll(collector)

        expect(afterBatch).toHaveBeenCalledTimes(2)
        expect(results).toHaveLength(3)
    })

    it('handles single-message batches', async () => {
        const collector = createCollector()

        collector.feed(makeBatch([42]))
        const results = await drainAll(collector)

        expect(beforeBatch).toHaveBeenCalledTimes(1)
        expect(afterBatch).toHaveBeenCalledTimes(1)
        expect(results).toHaveLength(1)
    })

    it('supports feed-drain-feed-drain cycle', async () => {
        const collector = createCollector()

        collector.feed(makeBatch([1]))
        const results1 = await drainAll(collector)
        expect(afterBatch).toHaveBeenCalledTimes(1)
        expect(results1).toHaveLength(1)

        collector.feed(makeBatch([2]))
        const results2 = await drainAll(collector)
        expect(afterBatch).toHaveBeenCalledTimes(2)
        expect(afterBatch.mock.calls[1][1]).toBe(1)
        expect(results2).toHaveLength(1)
    })

    it('awaits async afterBatch before returning from next()', async () => {
        const order: string[] = []

        afterBatch.mockImplementation(async () => {
            order.push('callback-start')
            await new Promise((r) => setTimeout(r, 10))
            order.push('callback-end')
        })

        const collector = createCollector()
        collector.feed(makeBatch([1]))

        order.push('next-called')
        await collector.next()
        order.push('next-resolved')

        expect(order).toEqual(['next-called', 'callback-start', 'callback-end', 'next-resolved'])
    })

    describe('with streaming sub-pipeline', () => {
        it('returns empty array when no batch completes on a next() call', async () => {
            const collector = createStreamingCollector()

            collector.feed(makeBatch([1, 2, 3]))

            // concurrently yields one result per next() call,
            // so first two calls don't complete the batch
            const first = await collector.next()
            expect(first).toEqual([])

            const second = await collector.next()
            expect(second).toEqual([])
        })

        it('fires afterBatch for first batch even when second is still in flight', async () => {
            const collector = createStreamingCollector()

            collector.feed(makeBatch([1]))
            collector.feed(makeBatch([2, 3]))

            // batch 0 has 1 element, completes on first next()
            const result0 = await collector.next()
            expect(afterBatch).toHaveBeenCalledTimes(1)
            expect(afterBatch.mock.calls[0][1]).toBe(0)
            expect(result0).toHaveLength(1)

            // batch 1 has 2 elements, still in flight
            const result1 = await collector.next()
            expect(afterBatch).toHaveBeenCalledTimes(1)
            expect(result1).toEqual([])

            // batch 1 completes
            const result2 = await collector.next()
            expect(afterBatch).toHaveBeenCalledTimes(2)
            expect(afterBatch.mock.calls[1][1]).toBe(1)
            expect(result2).toHaveLength(2)
            expect(result2![0].context.messageId).toBe(1)
            expect(result2![1].context.messageId).toBe(2)
        })

        it('returns results from multiple batches completing on the same next() call', async () => {
            const collector = createStreamingCollector()

            collector.feed(makeBatch([1]))
            collector.feed(makeBatch([2]))

            // Both batches are single-element. concurrently queues both promises.
            // First next() yields element from batch 0, completing batch 0.
            const result0 = await collector.next()
            expect(afterBatch).toHaveBeenCalledTimes(1)
            expect(result0).toHaveLength(1)

            // Second next() yields element from batch 1, completing batch 1.
            const result1 = await collector.next()
            expect(afterBatch).toHaveBeenCalledTimes(2)
            expect(result1).toHaveLength(1)
        })
    })

    it('beforeBatch can add extra context to elements', async () => {
        const collector = newBatchingPipeline<any, any, MsgCtx, string, SubCtx>(
            (elements, batchId) => ({
                batchContext: `store-for-batch-${batchId}`,
                elements: elements.map((el) => ({
                    ...el,
                    context: {
                        ...el.context,
                        batchStore: `store-for-batch-${batchId}`,
                    },
                })),
            }),
            (builder) => builder,
            () => {},
            { concurrentBatches: Infinity }
        )

        collector.feed(makeBatch([1, 2]))
        const results = await drainAll(collector)

        expect(results).toHaveLength(2)
        expect(results[0].context).toHaveProperty('batchStore', 'store-for-batch-0')
        expect(results[1].context).toHaveProperty('batchStore', 'store-for-batch-0')
        expect(results[0].context.messageId).toBe(0)
        expect(results[1].context.messageId).toBe(1)
    })

    it('passes batchContext from beforeBatch to afterBatch', async () => {
        type Stores = { personsStore: string; groupStore: string }

        const captured: Stores[] = []
        const collector = newBatchingPipeline<any, any, MsgCtx, Stores, SubCtx>(
            (elements, batchId) =>
                batch(elements, { personsStore: `persons-${batchId}`, groupStore: `groups-${batchId}` }),
            (builder) => builder,
            (batchContext) => {
                captured.push(batchContext)
            },
            { concurrentBatches: Infinity }
        )

        collector.feed(makeBatch([1]))
        collector.feed(makeBatch([2]))
        await drainAll(collector)

        expect(captured).toEqual([
            { personsStore: 'persons-0', groupStore: 'groups-0' },
            { personsStore: 'persons-1', groupStore: 'groups-1' },
        ])
    })

    describe('concurrentBatches', () => {
        it('feed() rejects with reason when at limit (default concurrentBatches: 1)', () => {
            const collector = createCollector({ concurrentBatches: 1 })

            expect(collector.feed(makeBatch([1]))).toEqual({ ok: true })
            expect(collector.feed(makeBatch([2]))).toMatchObject({ ok: false, reason: expect.any(String) })
        })

        it('draining a batch frees a slot', async () => {
            const collector = createCollector({ concurrentBatches: 1 })

            expect(collector.feed(makeBatch([1])).ok).toBe(true)
            expect(collector.feed(makeBatch([2])).ok).toBe(false)

            await drainAll(collector)

            expect(collector.feed(makeBatch([3])).ok).toBe(true)
        })

        it('feed() accepts when under limit and rejects when at limit', async () => {
            const collector = createCollector({ concurrentBatches: 2 })

            expect(collector.feed(makeBatch([1])).ok).toBe(true)
            expect(collector.feed(makeBatch([2])).ok).toBe(true)
            expect(collector.feed(makeBatch([3])).ok).toBe(false)

            await drainAll(collector)

            expect(collector.feed(makeBatch([4])).ok).toBe(true)
        })
    })
})
