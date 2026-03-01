import { Message } from 'node-rdkafka'

import { BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { BatchResult, BatchingContext, BatchingPipeline } from './batching-pipeline'
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

function noopBeforeBatch(
    _batchContext: Record<string, never>,
    elements: BatchPipelineResultWithContext<any, MsgCtx>,
    _batchId: number
): BatchResult<BatchPipelineResultWithContext<any, MsgCtx & BatchingContext>> {
    return { value: elements as any, sideEffects: [] }
}

function noopAfterBatch(): BatchResult<void> {
    return { value: undefined, sideEffects: [] }
}

describe('BatchingPipeline', () => {
    let beforeBatch: jest.Mock
    let afterBatch: jest.Mock

    beforeEach(() => {
        beforeBatch = jest.fn(noopBeforeBatch)
        afterBatch = jest.fn(noopAfterBatch)
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

    async function drainAll(
        pipeline: BatchingPipeline<any, any, any, any, any, any>
    ): Promise<{ allResults: PipelineResultWithContext<any, any>[]; allSideEffects: Promise<unknown>[] }> {
        const allResults: PipelineResultWithContext<any, any>[] = []
        const allSideEffects: Promise<unknown>[] = []
        let r = await pipeline.next()
        while (r !== null) {
            allResults.push(...r.value)
            allSideEffects.push(...r.sideEffects)
            r = await pipeline.next()
        }
        return { allResults, allSideEffects }
    }

    it('returns null when sub-pipeline is empty', async () => {
        const collector = createCollector()
        expect(await collector.next()).toBeNull()
        expect(beforeBatch).not.toHaveBeenCalled()
        expect(afterBatch).not.toHaveBeenCalled()
    })

    it('assigns sequential batch IDs to beforeBatch', () => {
        const collector = createCollector()

        collector.feed(makeBatch([1, 2]), {})
        collector.feed(makeBatch([3]), {})

        expect(beforeBatch).toHaveBeenCalledTimes(2)
        expect(beforeBatch.mock.calls[0][2]).toBe(0)
        expect(beforeBatch.mock.calls[0][1]).toHaveLength(2)
        expect(beforeBatch.mock.calls[1][2]).toBe(1)
        expect(beforeBatch.mock.calls[1][1]).toHaveLength(1)
    })

    it('tags each element with a monotonic messageId in context', async () => {
        const collector = createCollector()

        collector.feed(makeBatch([10, 20, 30]), {})
        const { allResults } = await drainAll(collector)

        expect(allResults).toHaveLength(3)
        expect(allResults[0].context.messageId).toBe(0)
        expect(allResults[1].context.messageId).toBe(1)
        expect(allResults[2].context.messageId).toBe(2)
    })

    it('continues messageId sequence across batches', async () => {
        const collector = createCollector()

        collector.feed(makeBatch([1, 2]), {})
        collector.feed(makeBatch([3]), {})
        const { allResults } = await drainAll(collector)

        expect(allResults).toHaveLength(3)
        expect(allResults[0].context.messageId).toBe(0)
        expect(allResults[1].context.messageId).toBe(1)
        expect(allResults[2].context.messageId).toBe(2)
    })

    it('returns ordered batch results when a batch completes', async () => {
        const collector = createCollector()

        collector.feed(makeBatch([1, 2, 3]), {})
        const { allResults } = await drainAll(collector)

        expect(afterBatch).toHaveBeenCalledTimes(1)
        expect(afterBatch.mock.calls[0][1]).toBe(0)
        expect(allResults).toHaveLength(3)
        expect(allResults[0].context.messageId).toBe(0)
        expect(allResults[1].context.messageId).toBe(1)
        expect(allResults[2].context.messageId).toBe(2)
    })

    it('tracks two batches independently', async () => {
        const collector = createCollector()

        collector.feed(makeBatch([1, 2]), {})
        collector.feed(makeBatch([3]), {})
        const { allResults } = await drainAll(collector)

        expect(afterBatch).toHaveBeenCalledTimes(2)
        expect(allResults).toHaveLength(3)
    })

    it('handles single-message batches', async () => {
        const collector = createCollector()

        collector.feed(makeBatch([42]), {})
        const { allResults } = await drainAll(collector)

        expect(beforeBatch).toHaveBeenCalledTimes(1)
        expect(afterBatch).toHaveBeenCalledTimes(1)
        expect(allResults).toHaveLength(1)
    })

    it('supports feed-drain-feed-drain cycle', async () => {
        const collector = createCollector()

        collector.feed(makeBatch([1]), {})
        const { allResults: results1 } = await drainAll(collector)
        expect(afterBatch).toHaveBeenCalledTimes(1)
        expect(results1).toHaveLength(1)

        collector.feed(makeBatch([2]), {})
        const { allResults: results2 } = await drainAll(collector)
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
            return { value: undefined, sideEffects: [] }
        })

        const collector = createCollector()
        collector.feed(makeBatch([1]), {})

        order.push('next-called')
        await collector.next()
        order.push('next-resolved')

        expect(order).toEqual(['next-called', 'callback-start', 'callback-end', 'next-resolved'])
    })

    describe('with streaming sub-pipeline', () => {
        it('blocks until a batch completes', async () => {
            const collector = createStreamingCollector()

            collector.feed(makeBatch([1, 2, 3]), {})

            // next() loops internally until a batch completes
            const result = await collector.next()
            expect(result).not.toBeNull()
            expect(result!.value).toHaveLength(3)
            expect(afterBatch).toHaveBeenCalledTimes(1)
        })

        it('fires afterBatch for first batch even when second is still in flight', async () => {
            const collector = createStreamingCollector()

            collector.feed(makeBatch([1]), {})
            collector.feed(makeBatch([2, 3]), {})

            // batch 0 has 1 element, next() loops until it completes
            const result0 = await collector.next()
            expect(afterBatch).toHaveBeenCalledTimes(1)
            expect(afterBatch.mock.calls[0][1]).toBe(0)
            expect(result0!.value).toHaveLength(1)

            // batch 1 has 2 elements, next() loops until it completes
            const result1 = await collector.next()
            expect(afterBatch).toHaveBeenCalledTimes(2)
            expect(afterBatch.mock.calls[1][1]).toBe(1)
            expect(result1!.value).toHaveLength(2)
            expect(result1!.value[0].context.messageId).toBe(1)
            expect(result1!.value[1].context.messageId).toBe(2)
        })

        it('returns results from multiple batches completing on the same next() call', async () => {
            const collector = createStreamingCollector()

            collector.feed(makeBatch([1]), {})
            collector.feed(makeBatch([2]), {})

            // Both batches are single-element. First next() may complete one or both.
            const result0 = await collector.next()
            expect(result0!.value).toHaveLength(1)

            const result1 = await collector.next()
            expect(result1!.value).toHaveLength(1)

            expect(afterBatch).toHaveBeenCalledTimes(2)
        })
    })

    it('beforeBatch can add extra context to elements', async () => {
        const collector = newBatchingPipeline<any, any, MsgCtx, string, SubCtx>(
            (_batchContext, elements, batchId) => ({
                value: elements.map((el) => ({
                    ...el,
                    context: {
                        ...el.context,
                        batchStore: `store-for-batch-${batchId}`,
                    },
                })),
                sideEffects: [],
            }),
            (builder) => builder,
            () => ({ value: undefined, sideEffects: [] }),
            { concurrentBatches: Infinity }
        )

        collector.feed(makeBatch([1, 2]), `store-for-batch-0`)
        const { allResults } = await drainAll(collector)

        expect(allResults).toHaveLength(2)
        expect(allResults[0].context).toHaveProperty('batchStore', 'store-for-batch-0')
        expect(allResults[1].context).toHaveProperty('batchStore', 'store-for-batch-0')
        expect(allResults[0].context.messageId).toBe(0)
        expect(allResults[1].context.messageId).toBe(1)
    })

    it('passes batchContext from feed() to beforeBatch and afterBatch', async () => {
        type Stores = { personsStore: string; groupStore: string }

        const capturedBefore: Stores[] = []
        const capturedAfter: Stores[] = []
        const collector = newBatchingPipeline<any, any, MsgCtx, Stores, SubCtx>(
            (batchContext, elements, _batchId) => {
                capturedBefore.push(batchContext)
                return { value: elements as any, sideEffects: [] }
            },
            (builder) => builder,
            (batchContext) => {
                capturedAfter.push(batchContext)
                return { value: undefined, sideEffects: [] }
            },
            { concurrentBatches: Infinity }
        )

        collector.feed(makeBatch([1]), { personsStore: 'persons-0', groupStore: 'groups-0' })
        collector.feed(makeBatch([2]), { personsStore: 'persons-1', groupStore: 'groups-1' })
        await drainAll(collector)

        expect(capturedBefore).toEqual([
            { personsStore: 'persons-0', groupStore: 'groups-0' },
            { personsStore: 'persons-1', groupStore: 'groups-1' },
        ])
        expect(capturedAfter).toEqual([
            { personsStore: 'persons-0', groupStore: 'groups-0' },
            { personsStore: 'persons-1', groupStore: 'groups-1' },
        ])
    })

    describe('side effects', () => {
        it('collects before hook side effects in next() result', async () => {
            const sideEffect = Promise.resolve('before-effect')
            beforeBatch.mockImplementation((_batchCtx: any, elements: any, _batchId: number) => ({
                value: elements,
                sideEffects: [sideEffect],
            }))

            const collector = createCollector()
            collector.feed(makeBatch([1]), {})

            const result = await collector.next()
            expect(result).not.toBeNull()
            expect(result!.sideEffects).toContain(sideEffect)
        })

        it('collects after hook side effects in next() result', async () => {
            const sideEffect = Promise.resolve('after-effect')
            afterBatch.mockImplementation(() => ({
                value: undefined,
                sideEffects: [sideEffect],
            }))

            const collector = createCollector()
            collector.feed(makeBatch([1]), {})

            const result = await collector.next()
            expect(result).not.toBeNull()
            expect(result!.sideEffects).toContain(sideEffect)
        })

        it('concatenates before and after side effects', async () => {
            const beforeEffect = Promise.resolve('before')
            const afterEffect = Promise.resolve('after')

            beforeBatch.mockImplementation((_batchCtx: any, elements: any, _batchId: number) => ({
                value: elements,
                sideEffects: [beforeEffect],
            }))
            afterBatch.mockImplementation(() => ({
                value: undefined,
                sideEffects: [afterEffect],
            }))

            const collector = createCollector()
            collector.feed(makeBatch([1]), {})

            const result = await collector.next()
            expect(result).not.toBeNull()
            expect(result!.sideEffects).toEqual([beforeEffect, afterEffect])
        })
    })

    describe('concurrentBatches', () => {
        it('feed() rejects with reason when at limit (default concurrentBatches: 1)', () => {
            const collector = createCollector({ concurrentBatches: 1 })

            expect(collector.feed(makeBatch([1]), {})).toEqual({ ok: true })
            expect(collector.feed(makeBatch([2]), {})).toMatchObject({ ok: false, reason: expect.any(String) })
        })

        it('draining a batch frees a slot', async () => {
            const collector = createCollector({ concurrentBatches: 1 })

            expect(collector.feed(makeBatch([1]), {}).ok).toBe(true)
            expect(collector.feed(makeBatch([2]), {}).ok).toBe(false)

            await drainAll(collector)

            expect(collector.feed(makeBatch([3]), {}).ok).toBe(true)
        })

        it('feed() accepts when under limit and rejects when at limit', async () => {
            const collector = createCollector({ concurrentBatches: 2 })

            expect(collector.feed(makeBatch([1]), {}).ok).toBe(true)
            expect(collector.feed(makeBatch([2]), {}).ok).toBe(true)
            expect(collector.feed(makeBatch([3]), {}).ok).toBe(false)

            await drainAll(collector)

            expect(collector.feed(makeBatch([4]), {}).ok).toBe(true)
        })
    })
})
