import { ClickHouseClient } from '@clickhouse/client'
import { DateTime } from 'luxon'

import { HogFlowManagerService } from '../services/hogflows/hogflow-manager.service'
import { CyclotronJobQueuePostgresV2 } from '../services/job-queue/job-queue-postgres-v2'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { HogFunctionManagerService } from '../services/managers/hog-function-manager.service'
import { HogFunctionMonitoringService } from '../services/monitoring/hog-function-monitoring.service'
import { HogInvocationResultsService } from '../services/monitoring/hog-invocation-results.service'
import { CyclotronJobInvocationHogFlow } from '../types'
import { RerunJobState } from './rerun-job.types'
import { RerunPaginatorService } from './rerun-paginator.service'

// A poisoned wait_until_condition the janitor gave up on is recorded with the
// FINAL flow state in `invocation_globals` — including `currentAction`, which is
// where the executor resumes from. If rerun rehydration dropped it, the flow
// would restart from the trigger and re-send emails that already went out. These
// tests pin the fix: the rehydrated invocation carries `currentAction` forward,
// so replay resumes after the already-completed actions.
describe('RerunPaginatorService replay fidelity (hog_flow)', () => {
    const teamId = 42
    const functionId = 'flow-1'

    function fakeClickhouse(rows: unknown[]): ClickHouseClient {
        return {
            query: jest.fn().mockResolvedValue({ json: () => Promise.resolve(rows) }),
        } as unknown as ClickHouseClient
    }

    function buildPaginator(
        clickhouse: ClickHouseClient,
        hogFlowQueue: jest.Mocked<CyclotronJobQueuePostgresV2>
    ): RerunPaginatorService {
        const hogFlowManager = {
            getHogFlow: jest.fn().mockResolvedValue({ id: functionId, team_id: teamId, variables: [] }),
        } as unknown as jest.Mocked<HogFlowManagerService>
        const hogFunctionManager = {
            getHogFunction: jest.fn().mockResolvedValue(null),
        } as unknown as jest.Mocked<HogFunctionManagerService>
        const lifecycle = {
            queueLifecycleRow: jest.fn(),
            queueRerunWrapperRow: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
            dropQueuedRowsFor: jest.fn(),
        } as unknown as jest.Mocked<HogInvocationResultsService>
        const monitoring = {
            queueLogs: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<HogFunctionMonitoringService>

        return new RerunPaginatorService(
            clickhouse,
            hogFunctionManager,
            hogFlowManager,
            lifecycle,
            { hog_function: {} as unknown as JobQueue, hog_flow: hogFlowQueue },
            monitoring,
            10000
        )
    }

    const state: RerunJobState = {
        function_kind: 'hog_flow',
        function_id: functionId,
        request: { filter: { window_start: '2026-01-01T00:00:00Z', window_end: '2027-01-01T00:00:00Z' } },
        progress: { queued: 0, skipped: 0, done: false },
    }

    it('restores currentAction and personId so a partially-run flow resumes instead of restarting', async () => {
        const persistedState = {
            event: { uuid: 'evt-1', distinct_id: 'd-1', properties: {}, timestamp: '2026-06-01T09:00:00Z' },
            actionStepCount: 3,
            variables: { ticket_id: '123' },
            // The flow had already advanced to (and parked at) the wait step.
            currentAction: { id: 'wait_condition', startedAtTimestamp: 999 },
            personId: 'person-1',
        }
        const rows = [
            {
                invocation_id: 'inv-1',
                parent_run_id: 'run-1',
                attempts: 0,
                last_scheduled_at: '2026-06-01 09:00:00.000000',
                first_scheduled_at: '2026-06-01 09:00:00.000000',
                // decodeInvocationGlobals treats a leading '{' as raw JSON.
                invocation_globals: JSON.stringify(persistedState),
            },
        ]

        const hogFlowQueue = {
            queueInvocations: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<CyclotronJobQueuePostgresV2>

        const paginator = buildPaginator(fakeClickhouse(rows), hogFlowQueue)
        await paginator.processPage(teamId, state, { jobId: 'rerun-1', createdAt: DateTime.now() })

        expect(hogFlowQueue.queueInvocations).toHaveBeenCalledTimes(1)
        const [enqueued, opts] = hogFlowQueue.queueInvocations.mock.calls[0]
        expect(opts).toEqual({ overwriteExisting: true })
        const invocation = enqueued[0] as CyclotronJobInvocationHogFlow
        expect(invocation.id).toBe('inv-1')
        // The resume point and per-actor context survive the round-trip.
        expect(invocation.state?.currentAction).toEqual(persistedState.currentAction)
        expect(invocation.state?.personId).toBe('person-1')
        expect(invocation.state?.actionStepCount).toBe(3)
        expect(invocation.state?.variables).toEqual({ ticket_id: '123' })
        // Sticky rerun counter still increments so max_attempts guards apply.
        expect(invocation.state?.rerunAttempts).toBe(1)
    })

    it('leaves currentAction undefined for a flow that never progressed (fresh start is correct there)', async () => {
        const persistedState = {
            event: { uuid: 'evt-2', distinct_id: 'd-2', properties: {}, timestamp: '2026-06-01T09:00:00Z' },
            actionStepCount: 0,
            variables: {},
        }
        const rows = [
            {
                invocation_id: 'inv-2',
                parent_run_id: '',
                attempts: 0,
                last_scheduled_at: '2026-06-01 09:00:00.000000',
                first_scheduled_at: '2026-06-01 09:00:00.000000',
                invocation_globals: JSON.stringify(persistedState),
            },
        ]

        const hogFlowQueue = {
            queueInvocations: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<CyclotronJobQueuePostgresV2>

        const paginator = buildPaginator(fakeClickhouse(rows), hogFlowQueue)
        await paginator.processPage(teamId, state, { jobId: 'rerun-2', createdAt: DateTime.now() })

        const invocation = hogFlowQueue.queueInvocations.mock.calls[0][0][0] as CyclotronJobInvocationHogFlow
        expect(invocation.state?.currentAction).toBeUndefined()
    })
})
