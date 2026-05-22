import { DateTime } from 'luxon'

import { CyclotronJobConflictError } from '../services/cyclotron-v2'
import { HogFlowManagerService } from '../services/hogflows/hogflow-manager.service'
import { CyclotronJobQueuePostgresV2 } from '../services/job-queue/job-queue-postgres-v2'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { HogFunctionManagerService } from '../services/managers/hog-function-manager.service'
import { HogFunctionMonitoringService } from '../services/monitoring/hog-function-monitoring.service'
import { HogInvocationResultsService } from '../services/monitoring/hog-invocation-results.service'
import { RerunFunctionKind, RerunJobState } from './rerun-job.types'
import { RerunPaginatorService } from './rerun-paginator.service'

/**
 * Unit tests for the paginator's re-enqueue routing. A rerun job is scoped to
 * one function kind, so a whole page routes to one backend — hog functions to
 * kafka, hog flows to postgres-v2, the same split cdp-events-consumer uses.
 *
 * ClickHouse + rehydration are stubbed (private `fetchPage` / `rehydrateBatch`)
 * so these run without infra; the real CH paths are covered by
 * `rerun-paginator.service.test.ts`.
 */
describe('RerunPaginatorService queue routing', () => {
    let hogQueue: jest.Mocked<JobQueue>
    let hogflowQueue: jest.Mocked<CyclotronJobQueuePostgresV2>
    let paginator: RerunPaginatorService

    beforeEach(() => {
        hogQueue = {
            queueInvocations: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<JobQueue>
        hogflowQueue = {
            queueInvocations: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<CyclotronJobQueuePostgresV2>

        const invocationResultsRowsService = {
            queueLifecycleRow: jest.fn(),
            queueRerunWrapperRow: jest.fn(),
            dropQueuedRowsFor: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<HogInvocationResultsService>

        const monitoringService = {
            queueLogs: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<HogFunctionMonitoringService>

        paginator = new RerunPaginatorService(
            {} as any,
            {} as unknown as HogFunctionManagerService,
            {} as unknown as HogFlowManagerService,
            invocationResultsRowsService,
            { hog_function: hogQueue, hog_flow: hogflowQueue },
            monitoringService,
            10000
        )
    })

    const buildState = (kind: RerunFunctionKind): RerunJobState => ({
        function_kind: kind,
        function_id: kind === 'hog_flow' ? 'flow-1' : 'fn-1',
        request: { filter: { window_start: '2026-01-01T00:00:00Z', window_end: '2027-01-01T00:00:00Z' } },
        progress: { queued: 0, skipped: 0, done: false },
    })

    // Stub the CH query + rehydration so the test exercises only the routing.
    const stubPage = (ids: string[]): void => {
        jest.spyOn(paginator as any, 'fetchPage').mockResolvedValue([])
        jest.spyOn(paginator as any, 'rehydrateBatch').mockResolvedValue({
            queued: ids.length,
            skipped: 0,
            queuedInvocations: ids.map((id) => ({ id })),
        })
    }

    const runPage = (state: RerunJobState) =>
        paginator.processPage(1, state, { jobId: 'test-rerun-job', createdAt: DateTime.now() })

    it('routes hog_function reruns to the kafka (hog) queue, not the hogflow queue', async () => {
        stubPage(['inv-1', 'inv-2'])

        await runPage(buildState('hog_function'))

        expect(hogQueue.queueInvocations).toHaveBeenCalledTimes(1)
        expect((hogQueue.queueInvocations.mock.calls[0][0] as any[]).map((i) => i.id)).toEqual(['inv-1', 'inv-2'])
        expect(hogflowQueue.queueInvocations).not.toHaveBeenCalled()
    })

    it('routes hog_flow reruns to the postgres-v2 (hogflow) queue with overwriteExisting', async () => {
        stubPage(['inv-1', 'inv-2'])

        await runPage(buildState('hog_flow'))

        expect(hogflowQueue.queueInvocations).toHaveBeenCalledTimes(1)
        expect((hogflowQueue.queueInvocations.mock.calls[0][0] as any[]).map((i) => i.id)).toEqual(['inv-1', 'inv-2'])
        // postgres-v2 re-enqueue re-uses the original invocation_id, so it must
        // upsert over the prior terminal row.
        expect(hogflowQueue.queueInvocations.mock.calls[0][1]).toEqual({ overwriteExisting: true })
        expect(hogQueue.queueInvocations).not.toHaveBeenCalled()
    })

    it('counts hogflow in-flight conflicts as skipped instead of failing the page', async () => {
        stubPage(['inv-conflict'])
        // The postgres-v2 upsert raises a conflict when the existing row is
        // still active — the paginator logs + counts it as a skip, not a failure.
        hogflowQueue.queueInvocations.mockRejectedValueOnce(new CyclotronJobConflictError('inv-conflict'))

        const { state: next } = await runPage(buildState('hog_flow'))

        expect(next.progress.queued).toBe(0)
        expect(next.progress.skipped).toBe(1)
        expect(next.progress.last_error).toBeUndefined()
    })
})
