import { HogFlowManagerService } from '../services/hogflows/hogflow-manager.service'
import { CyclotronJobQueuePostgresV2 } from '../services/job-queue/job-queue-postgres-v2'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { HogFunctionManagerService } from '../services/managers/hog-function-manager.service'
import { HogFunctionMonitoringService } from '../services/monitoring/hog-function-monitoring.service'
import { HogInvocationResultsService } from '../services/monitoring/hog-invocation-results.service'
import { WarpstreamHttpFetchService } from '../services/warpstream-http-fetch.service'
import { RerunPaginatorService } from './rerun-paginator.service'

/**
 * Unit tests for the paginator's by-reference globals resolution
 * (`resolveGlobalsByReference`). Exercises the private method directly with a
 * fake Warpstream fetcher so it runs without infra — the inline-column path and
 * end-to-end rehydration are covered by `rerun-paginator.service.test.ts`.
 */
describe('RerunPaginatorService globals-by-reference resolution', () => {
    const TOPIC = 'clickhouse_hog_invocation_results'

    const buildRow = (overrides: Partial<Record<string, unknown>> = {}): any => ({
        invocation_id: 'inv-1',
        parent_run_id: '',
        attempts: 0,
        last_scheduled_at: '2026-05-10 09:00:00.000000',
        first_scheduled_at: '2026-05-10 09:00:00.000000',
        invocation_globals: '{"inline":true}',
        globals_partition: 3,
        globals_offset: 42,
        ...overrides,
    })

    const message = (invocationId: string, globals: string): Buffer =>
        Buffer.from(JSON.stringify({ invocation_id: invocationId, invocation_globals: globals }))

    const buildPaginator = (fetcher: WarpstreamHttpFetchService | null): RerunPaginatorService =>
        new RerunPaginatorService(
            {} as any,
            {} as unknown as HogFunctionManagerService,
            {} as unknown as HogFlowManagerService,
            {} as unknown as HogInvocationResultsService,
            {
                hog_function: {} as unknown as JobQueue,
                hog_flow: {} as unknown as CyclotronJobQueuePostgresV2,
            },
            {} as unknown as HogFunctionMonitoringService,
            10000,
            fetcher,
            fetcher ? TOPIC : ''
        )

    const resolve = (paginator: RerunPaginatorService, rows: any[]): Promise<Map<string, string>> =>
        (paginator as any).resolveGlobalsByReference(rows)

    it('returns an empty map when no fetcher is configured', async () => {
        const resolved = await resolve(buildPaginator(null), [buildRow()])
        expect(resolved.size).toBe(0)
    })

    it('resolves globals from the fetched message keyed by partition:offset', async () => {
        const fetchRecords = jest.fn().mockResolvedValue(new Map([['3:42', message('inv-1', '"fetched"')]]))
        const fetcher = { fetchRecords } as unknown as WarpstreamHttpFetchService

        const resolved = await resolve(buildPaginator(fetcher), [buildRow()])

        expect(fetchRecords).toHaveBeenCalledWith(TOPIC, [{ partition: 3, offset: 42 }])
        expect(resolved.get('inv-1')).toBe('"fetched"')
    })

    it('ignores a fetched message whose invocation_id does not match the row', async () => {
        // Offset reused by an unrelated message (e.g. original aged out of
        // retention) — must not be trusted; the invocation is skipped.
        const fetchRecords = jest.fn().mockResolvedValue(new Map([['3:42', message('someone-else', '"wrong"')]]))
        const fetcher = { fetchRecords } as unknown as WarpstreamHttpFetchService

        const resolved = await resolve(buildPaginator(fetcher), [buildRow()])

        expect(resolved.has('inv-1')).toBe(false)
    })

    it('ignores a message with empty globals (a running-row message)', async () => {
        const fetchRecords = jest.fn().mockResolvedValue(new Map([['3:42', message('inv-1', '')]]))
        const fetcher = { fetchRecords } as unknown as WarpstreamHttpFetchService

        const resolved = await resolve(buildPaginator(fetcher), [buildRow()])

        expect(resolved.has('inv-1')).toBe(false)
    })

    it('requests an offset-0 ref (a valid first-message position) and resolves it', async () => {
        // With the column gone, (p, 0) is a genuine ref — the invocation_id check
        // (not an offset>0 filter) is what guards correctness.
        const fetchRecords = jest.fn().mockResolvedValue(new Map([['0:0', message('first', '"g"')]]))
        const fetcher = { fetchRecords } as unknown as WarpstreamHttpFetchService

        const resolved = await resolve(buildPaginator(fetcher), [
            buildRow({ invocation_id: 'first', globals_partition: 0, globals_offset: 0 }),
        ])

        expect(fetchRecords).toHaveBeenCalledWith(TOPIC, [{ partition: 0, offset: 0 }])
        expect(resolved.get('first')).toBe('"g"')
    })

    it('skips (absent from map) when a row is not in the fetch result', async () => {
        const fetchRecords = jest.fn().mockResolvedValue(new Map())
        const fetcher = { fetchRecords } as unknown as WarpstreamHttpFetchService

        const resolved = await resolve(buildPaginator(fetcher), [buildRow()])

        expect(resolved.has('inv-1')).toBe(false)
    })

    it('requests every row ref in one batched fetch', async () => {
        const fetchRecords = jest.fn().mockResolvedValue(new Map([['1:7', message('inv-b', '"b"')]]))
        const fetcher = { fetchRecords } as unknown as WarpstreamHttpFetchService

        await resolve(buildPaginator(fetcher), [
            buildRow({ invocation_id: 'inv-a', globals_partition: 0, globals_offset: 0 }),
            buildRow({ invocation_id: 'inv-b', globals_partition: 1, globals_offset: 7 }),
        ])

        expect(fetchRecords).toHaveBeenCalledWith(TOPIC, [
            { partition: 0, offset: 0 },
            { partition: 1, offset: 7 },
        ])
    })
})
