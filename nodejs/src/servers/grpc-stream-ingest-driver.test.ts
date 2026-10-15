import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { SubBatchBudget } from '~/ingestion/api/grpc-server'
import { BatchBudget } from '~/ingestion/framework/batch-budget'
import { PipelineResult, drop, ok, timeout } from '~/ingestion/framework/results'

import { GrpcIngestPipeline, GrpcStreamIngestDriver } from './grpc-stream-ingest-driver'

function completedBatch(results: PipelineResult<unknown>[]): GrpcIngestPipeline {
    return {
        next: () =>
            Promise.resolve({
                elements: results.map((result, index) => ({
                    result,
                    context: { message: { partition: 3, offset: 100 + index } },
                })),
                batchContext: { grpcStreamId: 7, grpcSeq: 3 },
                sideEffects: [],
            }),
    } as unknown as GrpcIngestPipeline
}

function recordingPipeline(fed: BatchBudget[]): GrpcIngestPipeline {
    return {
        feed: (_elements: unknown, _batchContext: unknown, budget: BatchBudget) => {
            fed.push(budget)
            return Promise.resolve({ ok: true })
        },
    } as unknown as GrpcIngestPipeline
}

describe('GrpcStreamIngestDriver', () => {
    describe('dispositions', () => {
        it('reports each timed-out element as unfinished by its partition and offset and counts the rest accepted', async () => {
            const driver = new GrpcStreamIngestDriver(
                completedBatch([ok({}), timeout('budget exceeded before step'), drop('not interesting')]),
                new PromiseScheduler()
            )

            const completed = (await driver.next())!

            expect(completed.streamId).toBe(7)
            expect(completed.seq).toBe(3)
            expect(completed.unfinished).toEqual([{ partition: 3, offset: 101 }])
            // A dropped element is handled, not redelivered, so it counts as accepted.
            expect(completed.accepted).toBe(2)
        })

        it('reports a fully processed batch with no dispositions', async () => {
            const driver = new GrpcStreamIngestDriver(completedBatch([ok({}), ok({})]), new PromiseScheduler())

            const completed = (await driver.next())!

            expect(completed.accepted).toBe(2)
            expect(completed.unfinished).toEqual([])
        })
    })

    describe('budgets', () => {
        async function fedBudget(wire: SubBatchBudget): Promise<BatchBudget> {
            const fed: BatchBudget[] = []
            const driver = new GrpcStreamIngestDriver(recordingPipeline(fed), new PromiseScheduler())

            await driver.feed(1, 1, [], wire)

            return fed[0]
        }

        it('anchors the deadline at the arming time, not at the feed', async () => {
            const budget = await fedBudget({ armedAt: 1_000, softBudgetMs: 200 })

            expect(budget.softAt).toBe(1_200)
        })

        it.each([
            ['zero', 0],
            ['longer than a timer can wait', 2 ** 31],
        ])('reads a %s allowance as an unlimited budget', async (_label, softBudgetMs) => {
            const budget = await fedBudget({ armedAt: 1_000, softBudgetMs })

            expect(budget.softAt).toBe(Infinity)
        })
    })
})
