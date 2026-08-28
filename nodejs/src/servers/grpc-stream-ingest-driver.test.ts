import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { SubBatchBudget } from '~/ingestion/api/grpc-server'
import { BatchBudget } from '~/ingestion/framework/batch-budget'

import { GrpcIngestPipeline, GrpcStreamIngestDriver } from './grpc-stream-ingest-driver'

/** A pipeline that records the budget each feed was given. */
function recordingPipeline(fed: BatchBudget[]): GrpcIngestPipeline {
    return {
        feed: (_elements: unknown, _batchContext: unknown, budget: BatchBudget) => {
            fed.push(budget)
            return Promise.resolve({ ok: true })
        },
    } as unknown as GrpcIngestPipeline
}

describe('GrpcStreamIngestDriver budgets', () => {
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

    it('reads a zero allowance as an unlimited budget', async () => {
        const budget = await fedBudget({ armedAt: 1_000, softBudgetMs: 0 })

        expect(budget.softAt).toBe(Infinity)
    })
})
