import { Message } from 'node-rdkafka'

import { createTestMessage } from '~/tests/helpers/kafka-message'

import { ChunkPipeline } from './chunk-pipeline.interface'
import { createNewChunkPipeline, createOkContext } from './helpers'
import { PipelineResultWithContext, PipelineWarning } from './pipeline.interface'
import { PipelineResult, dlq, drop, isDlqResult, isOkResult, ok } from './results'

interface Parent {
    id: string
    subs: number[]
}

interface SubItem {
    parentId: string
    value: number
}

interface Merged {
    id: string
    total: number
}

function splitSubs(parent: Parent): SubItem[] {
    return parent.subs.map((value) => ({ parentId: parent.id, value }))
}

function sumSubs(parent: Parent, results: SubItem[]): Merged {
    return { id: parent.id, total: results.reduce((acc, r) => acc + r.value, 0) }
}

function doubleStep(item: SubItem): Promise<PipelineResult<SubItem>> {
    return Promise.resolve(ok({ ...item, value: item.value * 2 }))
}

function deferred(): { promise: Promise<void>; resolve: () => void } {
    let resolve!: () => void
    const promise = new Promise<void>((r) => {
        resolve = r
    })
    return { promise, resolve }
}

function feedParents(pipeline: ChunkPipeline<Parent, unknown, { message: Message }>, parents: Parent[]): void {
    pipeline.feed(parents.map((parent) => createOkContext(parent, { message: createTestMessage() })))
}

async function drainAll<T, R extends string>(
    pipeline: ChunkPipeline<Parent, T, { message: Message }, { message: Message }, R>
): Promise<PipelineResultWithContext<T, { message: Message }, R>[]> {
    const all: PipelineResultWithContext<T, { message: Message }, R>[] = []
    let chunk = await pipeline.next()
    while (chunk !== null) {
        all.push(...chunk)
        chunk = await pipeline.next()
    }
    return all
}

function okValues<T, R extends string>(results: PipelineResultWithContext<T, { message: Message }, R>[]): T[] {
    return results.filter((r) => isOkResult(r.result)).map((r) => (r.result as { value: T }).value)
}

describe('FanOutFanInChunkPipeline', () => {
    it('fans out, processes subs, and fans results back in with one result per parent', async () => {
        const pipeline = createNewChunkPipeline<Parent>()
            .fanOutFanIn(splitSubs, (sub) => sub.concurrently((b) => b.pipe(doubleStep)), sumSubs)
            .build()

        feedParents(pipeline, [
            { id: 'a', subs: [1, 2, 3] },
            { id: 'b', subs: [4] },
            // Zero fan-out: completes immediately via fanInFn(parent, []).
            { id: 'c', subs: [] },
        ])

        const results = await drainAll(pipeline)

        expect(results).toHaveLength(3)
        expect(okValues(results)).toEqual(
            expect.arrayContaining([
                { id: 'a', total: 12 },
                { id: 'b', total: 8 },
                { id: 'c', total: 0 },
            ])
        )
    })

    it('passes non-OK parents through untouched, without fanning them out', async () => {
        const fannedOut: string[] = []
        function trackingFanOut(parent: Parent): SubItem[] {
            fannedOut.push(parent.id)
            return splitSubs(parent)
        }
        function dlqBadParentsStep(parents: Parent[]): Promise<PipelineResult<Parent>[]> {
            return Promise.resolve(parents.map((p) => (p.id === 'bad' ? dlq('bad parent') : ok(p))))
        }

        const pipeline = createNewChunkPipeline<Parent>()
            .pipeChunk(dlqBadParentsStep)
            .fanOutFanIn(trackingFanOut, (sub) => sub.concurrently((b) => b.pipe(doubleStep)), sumSubs)
            .build()

        feedParents(pipeline, [
            { id: 'good', subs: [1] },
            { id: 'bad', subs: [2] },
        ])

        const results = await drainAll(pipeline)

        expect(results).toHaveLength(2)
        const dlqResults = results.filter((r) => isDlqResult(r.result))
        expect(dlqResults).toHaveLength(1)
        expect(dlqResults[0].result).toMatchObject({ reason: 'bad parent' })
        expect(okValues(results)).toEqual([{ id: 'good', total: 2 }])
        expect(fannedOut).toEqual(['good'])
    })

    it('emits parents unordered as they complete, keeping sub-results correlated', async () => {
        const gate = deferred()
        function gatedStep(item: SubItem): Promise<PipelineResult<SubItem>> {
            if (item.parentId === 'slow') {
                return gate.promise.then(() => ok(item))
            }
            return Promise.resolve(ok(item))
        }

        // concurrentlyPerGroup reorders freely across groups, so completion
        // order (not fan-out order) drives parent emission — and each parent
        // must still collect exactly its own sub-results.
        const pipeline = createNewChunkPipeline<Parent>()
            .fanOutFanIn(
                splitSubs,
                (sub) =>
                    sub.concurrentlyPerGroup(
                        (item) => item.parentId,
                        (group) => group.sequentially((b) => b.pipe(gatedStep))
                    ),
                sumSubs
            )
            .build()

        feedParents(pipeline, [
            { id: 'slow', subs: [10, 20] },
            { id: 'fast', subs: [1, 2] },
        ])

        const first = await pipeline.next()
        expect(okValues(first!)).toEqual([{ id: 'fast', total: 3 }])

        gate.resolve()
        const second = await pipeline.next()
        expect(okValues(second!)).toEqual([{ id: 'slow', total: 30 }])

        expect(await pipeline.next()).toBeNull()
    })

    it('caps in-flight sub processing across parents via concurrently maxConcurrency', async () => {
        let inFlight = 0
        let highWater = 0
        async function trackingStep(item: SubItem): Promise<PipelineResult<SubItem>> {
            inFlight++
            highWater = Math.max(highWater, inFlight)
            await new Promise((resolve) => setImmediate(resolve))
            inFlight--
            return ok(item)
        }

        const pipeline = createNewChunkPipeline<Parent>()
            .fanOutFanIn(
                splitSubs,
                (sub) => sub.concurrently((b) => b.pipe(trackingStep), { maxConcurrency: 2 }),
                sumSubs
            )
            .build()

        feedParents(pipeline, [
            { id: 'a', subs: [1, 2, 3] },
            { id: 'b', subs: [4, 5, 6] },
        ])

        const results = await drainAll(pipeline)

        expect(okValues(results)).toEqual(
            expect.arrayContaining([
                { id: 'a', total: 6 },
                { id: 'b', total: 15 },
            ])
        )
        expect(highWater).toBeLessThanOrEqual(2)
    })

    it('recovers from transient sub-step failures via step retry options', async () => {
        let attempts = 0
        function flakyStep(item: SubItem): Promise<PipelineResult<SubItem>> {
            attempts++
            if (attempts === 1) {
                return Promise.reject(Object.assign(new Error('transient'), { isRetriable: true }))
            }
            return Promise.resolve(ok(item))
        }

        const pipeline = createNewChunkPipeline<Parent>()
            .fanOutFanIn(
                splitSubs,
                (sub) => sub.concurrently((b) => b.pipe(flakyStep, { retry: { tries: 3, sleepMs: 1 } })),
                sumSubs
            )
            .build()

        feedParents(pipeline, [{ id: 'a', subs: [7] }])

        const results = await drainAll(pipeline)

        expect(okValues(results)).toEqual([{ id: 'a', total: 7 }])
        expect(attempts).toBe(2)
    })

    it.each([
        ['dlq', dlq<SubItem>('first failure')],
        ['drop', drop<SubItem>('first failure')],
    ])('parent adopts the first non-OK sub-result (%s) and still drains its siblings', async (_name, nonOkResult) => {
        const siblingEffect = Promise.resolve('sibling')
        function failFirstSubStep(items: SubItem[]): Promise<PipelineResult<SubItem>[]> {
            return Promise.resolve(
                items.map((item) => {
                    if (item.parentId !== 'failing') {
                        return ok(item)
                    }
                    return item.value === 1 ? nonOkResult : ok(item, [siblingEffect])
                })
            )
        }

        const pipeline = createNewChunkPipeline<Parent>()
            .fanOutFanIn(splitSubs, (sub) => sub.pipeChunk(failFirstSubStep), sumSubs)
            .build()

        feedParents(pipeline, [
            { id: 'failing', subs: [1, 2] },
            { id: 'healthy', subs: [3] },
        ])

        const results = await drainAll(pipeline)

        expect(results).toHaveLength(2)
        const failed = results.find((r) => !isOkResult(r.result))!
        expect(failed.result).toBe(nonOkResult)
        // The sibling sub-result was drained: its side effect rode along on the
        // parent even though its value was discarded.
        expect(failed.context.sideEffects).toContain(siblingEffect)
        expect(okValues(results)).toEqual([{ id: 'healthy', total: 3 }])
    })

    it('merges sub side effects and warnings into the parent context without double-counting', async () => {
        const outerEffect = Promise.resolve('outer')
        function attachOuterEffectStep(parents: Parent[]): Promise<PipelineResult<Parent>[]> {
            return Promise.resolve(parents.map((p) => ok(p, [outerEffect])))
        }
        function warningStep(item: SubItem): Promise<PipelineResult<SubItem>> {
            const warning: PipelineWarning = {
                type: 'event_dropped_by_transformation',
                details: { value: item.value },
            }
            return Promise.resolve(ok(item, [Promise.resolve(item.value)], [warning]))
        }

        const pipeline = createNewChunkPipeline<Parent>()
            .pipeChunk(attachOuterEffectStep)
            .fanOutFanIn(splitSubs, (sub) => sub.concurrently((b) => b.pipe(warningStep)), sumSubs)
            .build()

        feedParents(pipeline, [{ id: 'a', subs: [1, 2] }])

        const results = await drainAll(pipeline)

        expect(results).toHaveLength(1)
        const context = results[0].context
        // One outer effect + one per sub — nothing duplicated by the fan-out.
        expect(context.sideEffects).toHaveLength(3)
        expect(context.sideEffects).toContain(outerEffect)
        expect(context.warnings).toEqual(
            expect.arrayContaining([
                { type: 'event_dropped_by_transformation', details: { value: 1 } },
                { type: 'event_dropped_by_transformation', details: { value: 2 } },
            ])
        )
        expect(context.warnings).toHaveLength(2)
    })

    it.each([
        [
            'fan-out function',
            () =>
                createNewChunkPipeline<Parent>()
                    .fanOutFanIn(
                        function throwingFanOut(): SubItem[] {
                            throw new Error('boom')
                        },
                        (sub) => sub.concurrently((b) => b.pipe(doubleStep)),
                        sumSubs
                    )
                    .build(),
        ],
        [
            'fan-in function',
            () =>
                createNewChunkPipeline<Parent>()
                    .fanOutFanIn(
                        splitSubs,
                        (sub) => sub.concurrently((b) => b.pipe(doubleStep)),
                        function throwingFanIn(): Merged {
                            throw new Error('boom')
                        }
                    )
                    .build(),
        ],
        [
            'sub step',
            () =>
                createNewChunkPipeline<Parent>()
                    .fanOutFanIn(
                        splitSubs,
                        (sub) =>
                            sub.concurrently((b) =>
                                b.pipe(function throwingStep(): Promise<PipelineResult<SubItem>> {
                                    return Promise.reject(new Error('boom'))
                                })
                            ),
                        sumSubs
                    )
                    .build(),
        ],
    ])('poisons the stage permanently when the %s throws', async (_name, createPipeline) => {
        const pipeline = createPipeline()

        feedParents(pipeline, [{ id: 'a', subs: [1] }])

        await expect(drainAll(pipeline)).rejects.toThrow('boom')
        await expect(pipeline.next()).rejects.toThrow('boom')
    })

    it('routes a batch fed while a prior parent is parked on slow subs', async () => {
        const gate = deferred()
        function gatedStep(item: SubItem): Promise<PipelineResult<SubItem>> {
            if (item.parentId === 'parked') {
                return gate.promise.then(() => ok(item))
            }
            return Promise.resolve(ok(item))
        }

        const pipeline = createNewChunkPipeline<Parent>()
            .fanOutFanIn(
                splitSubs,
                (sub) =>
                    sub.concurrentlyPerGroup(
                        (item) => item.parentId,
                        (group) => group.sequentially((b) => b.pipe(gatedStep))
                    ),
                sumSubs
            )
            .build()

        feedParents(pipeline, [{ id: 'parked', subs: [1] }])
        const firstPull = pipeline.next()

        // The stage is parked draining the parked parent; a fresh feed must
        // still get routed and complete ahead of it.
        feedParents(pipeline, [{ id: 'late', subs: [2] }])
        const first = await firstPull
        expect(okValues(first!)).toEqual([{ id: 'late', total: 2 }])

        gate.resolve()
        const second = await pipeline.next()
        expect(okValues(second!)).toEqual([{ id: 'parked', total: 1 }])
    })
})
