import { Message } from 'node-rdkafka'

import { logger } from '~/common/utils/logger'
import { createTestMessage } from '~/tests/helpers/kafka-message'

import { ChunkPipelineBuilder } from './builders'
import { ChunkPipeline } from './chunk-pipeline.interface'
import { FanOutFanInChunkPipeline, FanOutSubContext } from './fan-out-fan-in-chunk-pipeline'
import { createNewChunkPipeline, createOkContext } from './helpers'
import { PipelineResultWithContext, PipelineWarning } from './pipeline.interface'
import { PipelineResult, dlq, drop, isDlqResult, isOkResult, ok, redirect } from './results'

jest.mock('~/common/utils/logger', () => ({
    logger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))

const mockLogger = logger as jest.Mocked<typeof logger>

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
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('fans out, processes subs, and fans results back in with one result per parent', async () => {
        const pipeline = createNewChunkPipeline<Parent>()
            .fanOut(splitSubs)
            .via((sub) => sub.concurrently((b) => b.pipe(doubleStep)))
            .fanIn(sumSubs)
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
            .fanOut(trackingFanOut)
            .via((sub) => sub.concurrently((b) => b.pipe(doubleStep)))
            .fanIn(sumSubs)
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

    it('surfaces an empty upstream chunk as an empty chunk, not end of stream', async () => {
        // Direct construction with a mock upstream: [] chunks originate from
        // other stages (e.g. a filterMap passthrough), never from feed().
        const upstream: ChunkPipeline<Parent, Parent, { message: Message }> = {
            feed: jest.fn(),
            next: jest
                .fn()
                .mockResolvedValueOnce([])
                .mockResolvedValueOnce([createOkContext({ id: 'a', subs: [2] }, { message: createTestMessage() })])
                .mockResolvedValue(null),
        }
        const pipeline = new FanOutFanInChunkPipeline(
            upstream,
            splitSubs,
            createNewChunkPipeline<SubItem, FanOutSubContext>().build(),
            sumSubs
        )

        // Downstream treats null as "drained", so an empty chunk must surface
        // as [] — and must not stop the stage from processing later chunks.
        expect(await pipeline.next()).toEqual([])
        const second = await pipeline.next()
        expect(okValues(second!)).toEqual([{ id: 'a', total: 2 }])
        expect(await pipeline.next()).toBeNull()
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
            .fanOut(splitSubs)
            .via((sub) =>
                sub.concurrentlyPerGroup(
                    (item) => item.parentId,
                    (group) => group.sequentially((b) => b.pipe(gatedStep))
                )
            )
            .fanIn(sumSubs)
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

    it('silently excludes dropped sub-elements and fans in with the survivors', async () => {
        const dropEffect = Promise.resolve('dropped')
        function dropOddSubsStep(items: SubItem[]): Promise<PipelineResult<SubItem>[]> {
            return Promise.resolve(
                items.map((item) => (item.value % 2 === 1 ? drop<SubItem>('odd sub', [dropEffect]) : ok(item)))
            )
        }

        const pipeline = createNewChunkPipeline<Parent>()
            .fanOut(splitSubs)
            .via((sub) => sub.pipeChunk(dropOddSubsStep))
            .fanIn(sumSubs)
            .build()

        feedParents(pipeline, [{ id: 'a', subs: [1, 2, 3] }])

        const results = await drainAll(pipeline)

        // The parent always completes; dropped subs just contribute nothing.
        expect(okValues(results)).toEqual([{ id: 'a', total: 2 }])
        // The dropped sub-result's side effect still rode along on the parent.
        expect(results[0].context.sideEffects).toContain(dropEffect)
        expect(mockLogger.warn).not.toHaveBeenCalled()
    })

    it('excludes redirect sub-results with a warning and still completes the parent', async () => {
        const siblingEffect = Promise.resolve('sibling')
        function redirectFirstSubStep(items: SubItem[]): Promise<PipelineResult<SubItem, 'sub_redirect'>[]> {
            return Promise.resolve(
                items.map((item) => {
                    if (item.parentId !== 'redirecting') {
                        return ok(item)
                    }
                    return item.value === 1
                        ? redirect<SubItem, 'sub_redirect'>('sub failure', 'sub_redirect')
                        : ok(item, [siblingEffect])
                })
            )
        }

        const pipeline = createNewChunkPipeline<Parent>()
            .fanOut(splitSubs)
            .via((sub) => sub.pipeChunk(redirectFirstSubStep))
            .fanIn(sumSubs)
            .build()

        feedParents(pipeline, [
            { id: 'redirecting', subs: [1, 2] },
            { id: 'healthy', subs: [3] },
        ])

        const results = await drainAll(pipeline)

        // Both parents complete OK: the REDIRECT sub-result is excluded like a
        // drop, but loudly — it cannot become the parent's result.
        expect(results).toHaveLength(2)
        expect(okValues(results)).toEqual(
            expect.arrayContaining([
                { id: 'redirecting', total: 2 },
                { id: 'healthy', total: 3 },
            ])
        )
        const redirecting = results.find((r) => isOkResult(r.result) && r.result.value.id === 'redirecting')!
        expect(redirecting.context.sideEffects).toContain(siblingEffect)
        expect(mockLogger.warn).toHaveBeenCalledTimes(1)
        expect(mockLogger.warn).toHaveBeenCalledWith(
            '⚠️',
            'Fan-out subpipeline produced a redirect result; excluding it',
            {
                fanOutStep: 'splitSubs',
                fanInStep: 'sumSubs',
                resultType: 'REDIRECT',
                reason: 'sub failure',
            }
        )
    })

    it('dlqs the parent when a sub-result dlqs, aggregating after siblings drain', async () => {
        const siblingEffect = Promise.resolve('sibling')
        const subError = new Error('upload exploded')
        const fanInCalls: string[] = []
        function trackingFanIn(parent: Parent, subs: SubItem[]): Merged {
            fanInCalls.push(parent.id)
            return sumSubs(parent, subs)
        }
        function failFirstSubStep(items: SubItem[]): Promise<PipelineResult<SubItem>[]> {
            return Promise.resolve(
                items.map((item) => {
                    if (item.parentId !== 'failing') {
                        return ok(item)
                    }
                    return item.value === 1 ? dlq('sub failure', subError) : ok(item, [siblingEffect])
                })
            )
        }

        const pipeline = createNewChunkPipeline<Parent>()
            .fanOut(splitSubs)
            .via((sub) => sub.pipeChunk(failFirstSubStep))
            .fanIn(trackingFanIn)
            .build()

        feedParents(pipeline, [
            { id: 'failing', subs: [1, 2] },
            { id: 'healthy', subs: [3] },
        ])

        const results = await drainAll(pipeline)

        expect(results).toHaveLength(2)
        const failed = results.find((r) => isDlqResult(r.result))!
        if (!isDlqResult(failed.result)) {
            throw new Error('expected dlq result')
        }
        expect(failed.result.reason).toBe("1/2 fan-out sub-elements dlq'd: sub failure")
        expect(failed.result.error).toBeInstanceOf(AggregateError)
        expect((failed.result.error as AggregateError).errors).toEqual([subError])
        // The sibling drained first: its side effect rode along on the parent,
        // and error attribution points at the failing sub step.
        expect(failed.context.sideEffects).toContain(siblingEffect)
        expect(failed.context.lastStep).toBe('failFirstSubStep')
        // fanIn never ran for the failed parent — DLQ is first-class, no warn.
        expect(fanInCalls).toEqual(['healthy'])
        expect(okValues(results)).toEqual([{ id: 'healthy', total: 3 }])
        expect(mockLogger.warn).not.toHaveBeenCalled()
    })

    it.each([
        [
            'aggregates multiple dlq reasons with a count',
            (item: SubItem): PipelineResult<SubItem> => dlq(item.value === 2 ? 'r2' : 'r1'),
            "3/3 fan-out sub-elements dlq'd: r1; r2",
        ],
        [
            'dlqs the parent even when other subs are dropped',
            (item: SubItem): PipelineResult<SubItem> =>
                item.value === 1 ? dlq('r1') : item.value === 2 ? drop('skipped') : ok(item),
            "1/3 fan-out sub-elements dlq'd: r1",
        ],
    ])('%s', async (_name, resultFor, expectedReason) => {
        function mapSubStep(items: SubItem[]): Promise<PipelineResult<SubItem>[]> {
            return Promise.resolve(items.map(resultFor))
        }

        const pipeline = createNewChunkPipeline<Parent>()
            .fanOut(splitSubs)
            .via((sub) => sub.pipeChunk(mapSubStep))
            .fanIn(sumSubs)
            .build()

        feedParents(pipeline, [{ id: 'a', subs: [1, 2, 3] }])

        const results = await drainAll(pipeline)

        expect(results).toHaveLength(1)
        expect(isDlqResult(results[0].result) && results[0].result.reason).toBe(expectedReason)
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
            .fanOut(splitSubs)
            .via((sub) => sub.concurrently((b) => b.pipe(warningStep)))
            .fanIn(sumSubs)
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
                    .fanOut(function throwingFanOut(): SubItem[] {
                        throw new Error('boom')
                    })
                    .via((sub) => sub.concurrently((b) => b.pipe(doubleStep)))
                    .fanIn(sumSubs)
                    .build(),
        ],
        [
            'fan-in function',
            () =>
                createNewChunkPipeline<Parent>()
                    .fanOut(splitSubs)
                    .via((sub) => sub.concurrently((b) => b.pipe(doubleStep)))
                    .fanIn(function throwingFanIn(): Merged {
                        throw new Error('boom')
                    })
                    .build(),
        ],
        [
            'sub step',
            () =>
                createNewChunkPipeline<Parent>()
                    .fanOut(splitSubs)
                    .via((sub) =>
                        sub.concurrently((b) =>
                            b.pipe(function throwingStep(): Promise<PipelineResult<SubItem>> {
                                return Promise.reject(new Error('boom'))
                            })
                        )
                    )
                    .fanIn(sumSubs)
                    .build(),
        ],
    ])('poisons the stage permanently when the %s throws', async (_name, createPipeline) => {
        const pipeline = createPipeline()

        feedParents(pipeline, [{ id: 'a', subs: [1] }])

        await expect(drainAll(pipeline)).rejects.toThrow('boom')
        await expect(pipeline.next()).rejects.toThrow('boom')
    })

    it('drains completed parents before surfacing a later sub failure', async () => {
        function doomedStep(item: SubItem): Promise<PipelineResult<SubItem>> {
            if (item.parentId === 'doomed') {
                return Promise.reject(new Error('sub boom'))
            }
            return Promise.resolve(ok(item))
        }

        const pipeline = createNewChunkPipeline<Parent>()
            .fanOut(splitSubs)
            .via((sub) => sub.concurrently((b) => b.pipe(doomedStep)))
            .fanIn(sumSubs)
            .build()

        feedParents(pipeline, [
            { id: 'done', subs: [1] },
            { id: 'doomed', subs: [2] },
        ])

        // The failure is already in flight, but the completed parent must come
        // out first; only then does next() reject — permanently.
        const first = await pipeline.next()
        expect(okValues(first!)).toEqual([{ id: 'done', total: 1 }])
        await expect(pipeline.next()).rejects.toThrow('sub boom')
        await expect(pipeline.next()).rejects.toThrow('sub boom')
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
            .fanOut(splitSubs)
            .via((sub) =>
                sub.concurrentlyPerGroup(
                    (item) => item.parentId,
                    (group) => group.sequentially((b) => b.pipe(gatedStep))
                )
            )
            .fanIn(sumSubs)
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

// Type-level assertions: the fanOut → via → fanIn sequence is enforced by the
// type system — an unclosed stage exposes nothing but the next call, so there
// is no way to build (or leak) a stage that was never closed with fanIn. If a
// future edit widens the intermediate builders' surface, this stops compiling.
// Never executed.
function _stagedFanOutApiMustBeClosed(): void {
    const staged = createNewChunkPipeline<Parent>().fanOut(splitSubs)
    // @ts-expect-error fanIn is only available after via()
    const _noEarlyFanIn = staged.fanIn
    // @ts-expect-error an unclosed stage cannot be built
    const _noFanOutBuild = staged.build
    const routed = staged.via((sub) => {
        // @ts-expect-error sub-pipelines are context-agnostic — team-gated surface is uncallable
        sub.teamAware((b) => b)
        // @ts-expect-error sub-pipelines are context-agnostic — message-gated surface is uncallable
        sub.messageAware((b) => b)
        return sub.concurrently((b) => b.pipe(doubleStep))
    })
    // @ts-expect-error only fanIn can close the stage
    const _noFanInBuild = routed.build
    // @ts-expect-error the subpipeline surface is not available on the stage
    const _noPipeChunk = routed.pipeChunk
    // @ts-expect-error an unclosed stage is not a ChunkPipelineBuilder
    const _notABuilder: ChunkPipelineBuilder<Parent, SubItem, { message: Message }> = routed
}
