import { Message } from 'node-rdkafka'

import { OkResultWithContext } from './batch-pipeline.interface'
import { BatchingPipeline } from './batching-pipeline'
import { newBatchingPipeline } from './builders/helpers'
import { PipelineResultWithContext } from './pipeline.interface'
import { ok } from './results'

type MsgCtx = { message: Message }
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

function makeBatch(offsets: number[]): OkResultWithContext<any, MsgCtx>[] {
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
    let beforeBatchStep: jest.Mock
    let afterBatchStep: jest.Mock

    beforeEach(() => {
        beforeBatchStep = jest.fn(({ elements, batchContext }) => Promise.resolve(ok({ elements, batchContext })))
        afterBatchStep = jest.fn((input) =>
            Promise.resolve(ok({ elements: input.elements, batchContext: input.batchContext }))
        )
    })

    function createCollector(options?: { concurrentBatches?: number }) {
        return newBatchingPipeline<any, any, MsgCtx>(
            (builder) => builder.pipe(beforeBatchStep),
            (builder) => builder,
            (builder) => builder.pipe(afterBatchStep),
            { concurrentBatches: Infinity, ...options }
        )
    }

    function createStreamingCollector() {
        return newBatchingPipeline<any, any, MsgCtx>(
            (builder) => builder.pipe(beforeBatchStep),
            (builder) => builder.concurrently((b) => b.pipe((value) => Promise.resolve(ok(value)))),
            (builder) => builder.pipe(afterBatchStep),
            { concurrentBatches: Infinity }
        )
    }

    async function drainAll(
        pipeline: BatchingPipeline<any, any, any, any, any, never>
    ): Promise<{ allResults: PipelineResultWithContext<any, any>[]; allSideEffects: Promise<unknown>[] }> {
        const allResults: PipelineResultWithContext<any, any>[] = []
        const allSideEffects: Promise<unknown>[] = []
        let r = await pipeline.next()
        while (r !== null) {
            allResults.push(...r.elements)
            allSideEffects.push(...(r.sideEffects ?? []))
            r = await pipeline.next()
        }
        return { allResults, allSideEffects }
    }

    it('returns null when sub-pipeline is empty', async () => {
        const collector = createCollector()
        expect(await collector.next()).toBeNull()
        expect(beforeBatchStep).not.toHaveBeenCalled()
        expect(afterBatchStep).not.toHaveBeenCalled()
    })

    it('assigns sequential batch IDs to beforeBatch', async () => {
        const collector = createCollector()

        await collector.feed(makeBatch([1, 2]))
        await collector.feed(makeBatch([3]))

        expect(beforeBatchStep).toHaveBeenCalledTimes(2)
        expect(beforeBatchStep.mock.calls[0][0].batchContext.batchId).toBe(0)
        expect(beforeBatchStep.mock.calls[0][0].elements).toHaveLength(2)
        expect(beforeBatchStep.mock.calls[1][0].batchContext.batchId).toBe(1)
        expect(beforeBatchStep.mock.calls[1][0].elements).toHaveLength(1)
    })

    it('tags each element with a monotonic messageId in context', async () => {
        const collector = createCollector()

        await collector.feed(makeBatch([10, 20, 30]))
        const { allResults } = await drainAll(collector)

        expect(allResults).toHaveLength(3)
        expect(allResults[0].context.messageId).toBe(0)
        expect(allResults[1].context.messageId).toBe(1)
        expect(allResults[2].context.messageId).toBe(2)
    })

    it('continues messageId sequence across batches', async () => {
        const collector = createCollector()

        await collector.feed(makeBatch([1, 2]))
        await collector.feed(makeBatch([3]))
        const { allResults } = await drainAll(collector)

        expect(allResults).toHaveLength(3)
        expect(allResults[0].context.messageId).toBe(0)
        expect(allResults[1].context.messageId).toBe(1)
        expect(allResults[2].context.messageId).toBe(2)
    })

    it('returns ordered batch results when a batch completes', async () => {
        const collector = createCollector()

        await collector.feed(makeBatch([1, 2, 3]))
        const { allResults } = await drainAll(collector)

        expect(afterBatchStep).toHaveBeenCalledTimes(1)
        expect(afterBatchStep.mock.calls[0][0].batchId).toBe(0)
        expect(allResults).toHaveLength(3)
        expect(allResults[0].context.messageId).toBe(0)
        expect(allResults[1].context.messageId).toBe(1)
        expect(allResults[2].context.messageId).toBe(2)
    })

    it('tracks two batches independently', async () => {
        const collector = createCollector()

        await collector.feed(makeBatch([1, 2]))
        await collector.feed(makeBatch([3]))
        const { allResults } = await drainAll(collector)

        expect(afterBatchStep).toHaveBeenCalledTimes(2)
        expect(allResults).toHaveLength(3)
    })

    it('handles single-message batches', async () => {
        const collector = createCollector()

        await collector.feed(makeBatch([42]))
        const { allResults } = await drainAll(collector)

        expect(beforeBatchStep).toHaveBeenCalledTimes(1)
        expect(afterBatchStep).toHaveBeenCalledTimes(1)
        expect(allResults).toHaveLength(1)
    })

    it('supports feed-drain-feed-drain cycle', async () => {
        const collector = createCollector()

        await collector.feed(makeBatch([1]))
        const { allResults: results1 } = await drainAll(collector)
        expect(afterBatchStep).toHaveBeenCalledTimes(1)
        expect(results1).toHaveLength(1)

        await collector.feed(makeBatch([2]))
        const { allResults: results2 } = await drainAll(collector)
        expect(afterBatchStep).toHaveBeenCalledTimes(2)
        expect(afterBatchStep.mock.calls[1][0].batchId).toBe(1)
        expect(results2).toHaveLength(1)
    })

    it('awaits async afterBatch before returning from next()', async () => {
        const order: string[] = []

        afterBatchStep.mockImplementation(async (input: any) => {
            order.push('callback-start')
            await new Promise((r) => setTimeout(r, 10))
            order.push('callback-end')
            return ok({ elements: input.elements, batchContext: input.batchContext })
        })

        const collector = createCollector()
        await collector.feed(makeBatch([1]))

        order.push('next-called')
        await collector.next()
        order.push('next-resolved')

        expect(order).toEqual(['next-called', 'callback-start', 'callback-end', 'next-resolved'])
    })

    describe('with streaming sub-pipeline', () => {
        it('blocks until a batch completes', async () => {
            const collector = createStreamingCollector()

            await collector.feed(makeBatch([1, 2, 3]))

            const result = await collector.next()
            expect(result).not.toBeNull()
            expect(result!.elements).toHaveLength(3)
            expect(afterBatchStep).toHaveBeenCalledTimes(1)
        })

        it('fires afterBatch for first batch even when second is still in flight', async () => {
            const collector = createStreamingCollector()

            await collector.feed(makeBatch([1]))
            await collector.feed(makeBatch([2, 3]))

            const result0 = await collector.next()
            expect(afterBatchStep).toHaveBeenCalledTimes(1)
            expect(afterBatchStep.mock.calls[0][0].batchId).toBe(0)
            expect(result0!.elements).toHaveLength(1)

            const result1 = await collector.next()
            expect(afterBatchStep).toHaveBeenCalledTimes(2)
            expect(afterBatchStep.mock.calls[1][0].batchId).toBe(1)
            expect(result1!.elements).toHaveLength(2)
            expect(result1!.elements[0].context.messageId).toBe(1)
            expect(result1!.elements[1].context.messageId).toBe(2)
        })

        it('returns results from multiple batches completing on the same next() call', async () => {
            const collector = createStreamingCollector()

            await collector.feed(makeBatch([1]))
            await collector.feed(makeBatch([2]))

            const result0 = await collector.next()
            expect(result0!.elements).toHaveLength(1)

            const result1 = await collector.next()
            expect(result1!.elements).toHaveLength(1)

            expect(afterBatchStep).toHaveBeenCalledTimes(2)
        })
    })

    it('beforeBatch can add extra context to elements', async () => {
        type BatchStore = { batchStore: string }
        const collector = newBatchingPipeline<any, any, MsgCtx, BatchStore>(
            (builder) =>
                builder.pipe(({ elements, batchContext }) =>
                    Promise.resolve(
                        ok({
                            elements: elements.map((el: any) => ({
                                ...el,
                                context: {
                                    ...el.context,
                                    batchStore: `store-for-batch-${batchContext.batchId}`,
                                },
                            })),
                            batchContext: { ...batchContext, batchStore: `store-for-batch-${batchContext.batchId}` },
                        })
                    )
                ),
            (builder) => builder,
            (builder) => builder.pipe((input) => Promise.resolve(ok(input))),
            { concurrentBatches: Infinity }
        )

        await collector.feed(makeBatch([1, 2]))
        const { allResults } = await drainAll(collector)

        expect(allResults).toHaveLength(2)
        expect(allResults[0].context).toHaveProperty('batchStore', 'store-for-batch-0')
        expect(allResults[1].context).toHaveProperty('batchStore', 'store-for-batch-0')
        expect(allResults[0].context.messageId).toBe(0)
        expect(allResults[1].context.messageId).toBe(1)
    })

    it('passes batchContext from beforeBatch to afterBatch', async () => {
        type Stores = { personsStore: string; groupStore: string }

        const capturedBefore: Stores[] = []
        const capturedAfter: Stores[] = []
        const collector = newBatchingPipeline<any, any, MsgCtx, Stores>(
            (builder) =>
                builder.pipe(({ elements, batchContext: initBatchContext }) => {
                    const stores: Stores =
                        initBatchContext.batchId === 0
                            ? { personsStore: 'persons-0', groupStore: 'groups-0' }
                            : { personsStore: 'persons-1', groupStore: 'groups-1' }
                    const batchContext = { ...initBatchContext, ...stores }
                    capturedBefore.push(stores)
                    return Promise.resolve(ok({ elements: elements as any, batchContext }))
                }),
            (builder) => builder,
            (builder) =>
                builder.pipe((input) => {
                    capturedAfter.push(input.batchContext)
                    return Promise.resolve(ok(input))
                }),
            { concurrentBatches: Infinity }
        )

        await collector.feed(makeBatch([1]))
        await collector.feed(makeBatch([2]))
        await drainAll(collector)

        expect(capturedBefore).toEqual([
            { personsStore: 'persons-0', groupStore: 'groups-0' },
            { personsStore: 'persons-1', groupStore: 'groups-1' },
        ])
        expect(capturedAfter).toEqual([
            expect.objectContaining({ personsStore: 'persons-0', groupStore: 'groups-0' }),
            expect.objectContaining({ personsStore: 'persons-1', groupStore: 'groups-1' }),
        ])
    })

    describe('side effects', () => {
        it('collects before pipeline side effects in next() result', async () => {
            const sideEffect = Promise.resolve('before-effect')
            beforeBatchStep.mockImplementation(({ elements, batchContext }: any) =>
                ok({ elements, batchContext }, [sideEffect])
            )

            const collector = createCollector()
            await collector.feed(makeBatch([1]))

            const result = await collector.next()
            expect(result).not.toBeNull()
            expect(result!.sideEffects).toContain(sideEffect)
        })

        it('collects after pipeline side effects in next() result', async () => {
            const sideEffect = Promise.resolve('after-effect')
            afterBatchStep.mockImplementation((input: any) =>
                ok({ elements: input.elements, batchContext: input.batchContext }, [sideEffect])
            )

            const collector = createCollector()
            await collector.feed(makeBatch([1]))

            const result = await collector.next()
            expect(result).not.toBeNull()
            expect(result!.sideEffects).toContain(sideEffect)
        })

        it('concatenates before and after side effects', async () => {
            const beforeEffect = Promise.resolve('before')
            const afterEffect = Promise.resolve('after')

            beforeBatchStep.mockImplementation(({ elements, batchContext }: any) =>
                ok({ elements, batchContext }, [beforeEffect])
            )
            afterBatchStep.mockImplementation((input: any) =>
                ok({ elements: input.elements, batchContext: input.batchContext }, [afterEffect])
            )

            const collector = createCollector()
            await collector.feed(makeBatch([1]))

            const result = await collector.next()
            expect(result).not.toBeNull()
            expect(result!.sideEffects).toEqual([beforeEffect, afterEffect])
        })
    })

    describe('empty and count-changing batches', () => {
        // An empty feed used to register an un-completable batch: next() then
        // threw the "null with N in-flight batches" corruption guard, and the
        // phantom batch permanently occupied a concurrentBatches slot so every
        // later feed() was rejected.
        it('empty feed is a no-op that skips hooks and does not leak a capacity slot', async () => {
            const collector = createCollector({ concurrentBatches: 1 })

            expect(await collector.feed([])).toEqual({ ok: true })
            expect(beforeBatchStep).not.toHaveBeenCalled()
            expect(await collector.next()).toBeNull()

            // The slot was not leaked: a subsequent normal batch is accepted and processed.
            expect(await collector.feed(makeBatch([9]))).toEqual({ ok: true })
            const { allResults } = await drainAll(collector)
            expect(allResults).toHaveLength(1)
            expect(afterBatchStep).toHaveBeenCalledTimes(1)
        })

        // beforeBatch must preserve the element count; a shrunken batch (worst
        // case zero elements) could never complete and would leak its slot.
        it('rejects a beforeBatch that changes the element count without leaking a capacity slot', async () => {
            beforeBatchStep.mockImplementationOnce(({ elements, batchContext }: any) =>
                Promise.resolve(ok({ elements: elements.slice(1), batchContext }))
            )
            const collector = createCollector({ concurrentBatches: 1 })

            expect(await collector.feed(makeBatch([1, 2]))).toEqual({
                ok: false,
                kind: 'before_batch_failed',
                reason: expect.stringContaining('changed element count (2 -> 1)'),
            })
            expect(await collector.next()).toBeNull()

            // Nothing was registered: a subsequent normal batch is accepted and processed.
            expect(await collector.feed(makeBatch([9]))).toEqual({ ok: true })
            const { allResults } = await drainAll(collector)
            expect(allResults).toHaveLength(1)
            expect(afterBatchStep).toHaveBeenCalledTimes(1)
        })
    })

    describe('concurrentBatches', () => {
        it('feed() rejects with reason when at limit (default concurrentBatches: 1)', async () => {
            const collector = createCollector({ concurrentBatches: 1 })

            expect(await collector.feed(makeBatch([1]))).toEqual({ ok: true })
            expect(await collector.feed(makeBatch([2]))).toMatchObject({ ok: false, reason: expect.any(String) })
        })

        it('draining a batch frees a slot', async () => {
            const collector = createCollector({ concurrentBatches: 1 })

            expect((await collector.feed(makeBatch([1]))).ok).toBe(true)
            expect((await collector.feed(makeBatch([2]))).ok).toBe(false)

            await drainAll(collector)

            expect((await collector.feed(makeBatch([3]))).ok).toBe(true)
        })

        it('feed() accepts when under limit and rejects when at limit', async () => {
            const collector = createCollector({ concurrentBatches: 2 })

            expect((await collector.feed(makeBatch([1]))).ok).toBe(true)
            expect((await collector.feed(makeBatch([2]))).ok).toBe(true)
            expect((await collector.feed(makeBatch([3]))).ok).toBe(false)

            await drainAll(collector)

            expect((await collector.feed(makeBatch([4]))).ok).toBe(true)
        })
    })
})
