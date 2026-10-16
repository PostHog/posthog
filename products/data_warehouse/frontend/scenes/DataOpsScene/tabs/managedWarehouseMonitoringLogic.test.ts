import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'

import { teamLogic } from 'scenes/teamLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import {
    dataWarehouseManagedWarehouseMonitoringRetrieve,
    dataWarehouseManagedWarehouseMonitoringTimeseriesRetrieve,
} from 'products/data_warehouse/frontend/generated/api'
import type {
    DataWarehouseManagedWarehouseMonitoringTimeseriesRetrieveParams,
    ManagedWarehouseMonitoringSeriesResponseApi,
    ManagedWarehouseMonitoringSnapshotResponseApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import { managedWarehouseMonitoringLogic } from './managedWarehouseMonitoringLogic'

jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    dataWarehouseManagedWarehouseMonitoringRetrieve: jest.fn(),
    dataWarehouseManagedWarehouseMonitoringTimeseriesRetrieve: jest.fn(),
}))

const mockSnapshotRetrieve = dataWarehouseManagedWarehouseMonitoringRetrieve as jest.MockedFunction<
    typeof dataWarehouseManagedWarehouseMonitoringRetrieve
>
const mockSeriesRetrieve = dataWarehouseManagedWarehouseMonitoringTimeseriesRetrieve as jest.MockedFunction<
    typeof dataWarehouseManagedWarehouseMonitoringTimeseriesRetrieve
>

function snapshot({
    organizationId = 'org-1',
    runningQueries = 0,
}: {
    organizationId?: string
    runningQueries?: number
} = {}): ManagedWarehouseMonitoringSnapshotResponseApi {
    return {
        schema_version: 1,
        org_id: organizationId,
        as_of: '2026-08-12T10:00:00Z',
        warehouse: { state: 'ready' },
        limits: {
            max_workers: 10,
            max_vcpus: 20,
            default_worker_cpu: '2',
            default_worker_memory: '8Gi',
            default_worker_ttl_seconds: 300,
            default_worker_min_hot_idle: 1,
        },
        totals: {
            workers: 1,
            allocated_cpu_cores: 2,
            allocated_memory_bytes: 8 * 1024 ** 3,
            active_sessions: runningQueries,
            running_queries: runningQueries,
            queued_connections: 0,
        },
        workers: [
            {
                id: `worker-${organizationId}`,
                state: 'hot',
                cpu: '2',
                memory: '8Gi',
                ttl_seconds: 300,
                created_at: '2026-08-12T09:55:00Z',
                last_heartbeat_at: '2026-08-12T10:00:00Z',
                session: null,
            },
        ],
        coverage: { cp_responders: 2, cp_total: 2, partial: false },
    }
}

function seriesResponse(
    metric: DataWarehouseManagedWarehouseMonitoringTimeseriesRetrieveParams['metric'],
    organizationId = 'org-1'
): ManagedWarehouseMonitoringSeriesResponseApi {
    return {
        schema_version: 1,
        org_id: organizationId,
        metric,
        unit: 'count',
        start: '2026-08-12T09:59:00Z',
        end: '2026-08-12T10:00:00Z',
        step_seconds: 60,
        series: [
            {
                labels: {},
                points: [
                    { timestamp: '2026-08-12T09:59:00Z', value: 1 },
                    { timestamp: '2026-08-12T10:00:00Z', value: 2 },
                ],
            },
        ],
    }
}

describe('managedWarehouseMonitoringLogic', () => {
    let logic: ReturnType<typeof managedWarehouseMonitoringLogic.build>

    const mountLogic = (): void => {
        logic = managedWarehouseMonitoringLogic()
        logic.mount()
    }

    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        mockSnapshotRetrieve.mockReset()
        mockSeriesRetrieve.mockReset()
        mockSnapshotRetrieve.mockImplementation(async (teamId) => snapshot({ organizationId: `org-${teamId}` }))
        mockSeriesRetrieve.mockImplementation(async (teamId, { metric }) => seriesResponse(metric, `org-${teamId}`))
    })

    afterEach(() => {
        logic?.unmount()
        resumeKeaLoadersErrors()
        jest.useRealTimers()
    })

    it('loads the live snapshot and every displayed series on mount', async () => {
        mountLogic()

        expect(logic.values.monitoringSnapshotLoading).toBe(true)
        expect(logic.values.monitoringSeriesLoading).toBe(true)

        await jest.advanceTimersByTimeAsync(0)

        expect(mockSnapshotRetrieve).toHaveBeenCalledWith(String(MOCK_TEAM_ID))
        expect(mockSeriesRetrieve).toHaveBeenCalledTimes(8)
        expect(mockSeriesRetrieve.mock.calls.map(([, { metric }]) => metric)).toEqual([
            'query_rate',
            'error_ratio',
            'duration_p50',
            'duration_p95',
            'sessions_active',
            'acquire_p95',
            'storage_bytes',
            'worker_crash_rate',
        ])
        expect(logic.values.monitoringSnapshot?.org_id).toBe(`org-${MOCK_TEAM_ID}`)
        expect(logic.values.monitoringSeries).toHaveLength(8)
    })

    it.each([
        { name: 'active work', runningQueries: 1, intervalMs: 15_000 },
        { name: 'stable warehouse', runningQueries: 0, intervalMs: 60_000 },
    ])('polls the snapshot at the expected interval for $name', async ({ runningQueries, intervalMs }) => {
        mockSnapshotRetrieve.mockResolvedValue(snapshot({ runningQueries }))
        mountLogic()
        await jest.advanceTimersByTimeAsync(0)

        await jest.advanceTimersByTimeAsync(intervalMs - 1)
        expect(mockSnapshotRetrieve).toHaveBeenCalledTimes(1)

        await jest.advanceTimersByTimeAsync(1)
        expect(mockSnapshotRetrieve).toHaveBeenCalledTimes(2)
    })

    it('reloads every series when the time window changes', async () => {
        mountLogic()
        await jest.advanceTimersByTimeAsync(0)
        const previousSeries = logic.values.monitoringSeries
        mockSeriesRetrieve.mockClear()
        mockSeriesRetrieve.mockImplementation(async (teamId, { metric }) => {
            if (metric === 'error_ratio') {
                throw new Error('metric unavailable')
            }
            return seriesResponse(metric, `org-${teamId}`)
        })

        logic.actions.setMonitoringWindow('7d')
        expect(logic.values.monitoringSeries).toBe(previousSeries)
        expect(logic.values.monitoringSeriesLoading).toBe(true)
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.monitoringWindow).toBe('7d')
        expect(logic.values.monitoringSeriesWindow).toBe('7d')
        expect(mockSeriesRetrieve).toHaveBeenCalledTimes(8)
        expect(mockSeriesRetrieve.mock.calls.every(([, params]) => params.window === '7d')).toBe(true)
        expect(logic.values.monitoringSeries).toHaveLength(7)
        expect(logic.values.monitoringSeries.some((response) => response.metric === 'error_ratio')).toBe(false)
    })

    it('keeps settled empty charts stable while retrying after a series error', async () => {
        silenceKeaLoadersErrors()
        mockSeriesRetrieve.mockRejectedValue(new Error('series unavailable'))
        mountLogic()

        expect(logic.values.initialMonitoringSeriesLoading).toBe(true)
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.monitoringSeries).toEqual([])
        expect(logic.values.monitoringSeriesError).toBe(true)
        expect(logic.values.monitoringSeriesResolved).toBe(true)
        expect(logic.values.initialMonitoringSeriesLoading).toBe(false)

        logic.actions.setMonitoringWindow('7d')

        expect(logic.values.monitoringSeriesLoading).toBe(true)
        expect(logic.values.monitoringSeriesError).toBe(true)
        expect(logic.values.initialMonitoringSeriesLoading).toBe(false)
        await jest.advanceTimersByTimeAsync(0)
    })

    it('keeps the previous value for a metric when other metrics refresh successfully', async () => {
        mountLogic()
        await jest.advanceTimersByTimeAsync(0)
        const previousErrorRatio = logic.values.monitoringSeries.find((response) => response.metric === 'error_ratio')
        mockSeriesRetrieve.mockImplementation(async (teamId, { metric }) => {
            if (metric === 'error_ratio') {
                throw new Error('metric unavailable')
            }
            return seriesResponse(metric, `org-${teamId}`)
        })

        logic.actions.refreshMonitoring()
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.monitoringSeries).toHaveLength(8)
        expect(logic.values.monitoringSeries.find((response) => response.metric === 'error_ratio')).toBe(
            previousErrorRatio
        )
        expect(logic.values.monitoringSeriesError).toBe(true)
    })

    it('keeps the last good data and marks each section when refreshes fail', async () => {
        silenceKeaLoadersErrors()
        mountLogic()
        await jest.advanceTimersByTimeAsync(0)
        const previousSnapshot = logic.values.monitoringSnapshot
        const previousSeries = logic.values.monitoringSeries
        mockSnapshotRetrieve.mockRejectedValueOnce(new Error('snapshot unavailable'))
        mockSeriesRetrieve.mockRejectedValue(new Error('series unavailable'))

        logic.actions.refreshMonitoring()
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.monitoringSnapshot).toBe(previousSnapshot)
        expect(logic.values.monitoringSeries).toBe(previousSeries)
        expect(logic.values.monitoringSnapshotError).toBe(true)
        expect(logic.values.monitoringSeriesError).toBe(true)
    })

    it('stops polling after unmount', async () => {
        mountLogic()
        await jest.advanceTimersByTimeAsync(0)
        const snapshotCalls = mockSnapshotRetrieve.mock.calls.length
        const seriesCalls = mockSeriesRetrieve.mock.calls.length

        logic.unmount()
        await jest.advanceTimersByTimeAsync(120_000)

        expect(mockSnapshotRetrieve).toHaveBeenCalledTimes(snapshotCalls)
        expect(mockSeriesRetrieve).toHaveBeenCalledTimes(seriesCalls)
    })

    it('clears organization data before loading it for a new team', async () => {
        mountLogic()
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values.monitoringSnapshot?.org_id).toBe(`org-${MOCK_TEAM_ID}`)

        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            id: 1234,
            project_id: 1234,
            organization: 'org-2',
        })

        expect(logic.values.monitoringSnapshot).toBeNull()
        expect(logic.values.monitoringSeries).toEqual([])

        await jest.advanceTimersByTimeAsync(0)
        expect(mockSnapshotRetrieve).toHaveBeenLastCalledWith('1234')
        expect(logic.values.monitoringSnapshot?.org_id).toBe('org-1234')
        expect(logic.values.monitoringSeries.every((response) => response.org_id === 'org-1234')).toBe(true)
    })

    it('ignores responses from requests superseded by a team change', async () => {
        let resolveOldSnapshot: ((value: ManagedWarehouseMonitoringSnapshotResponseApi) => void) | undefined
        const oldSeriesResolvers = new Map<
            DataWarehouseManagedWarehouseMonitoringTimeseriesRetrieveParams['metric'],
            (value: ManagedWarehouseMonitoringSeriesResponseApi) => void
        >()
        mockSnapshotRetrieve.mockImplementation(
            async (teamId) =>
                await (teamId === String(MOCK_TEAM_ID)
                    ? new Promise<ManagedWarehouseMonitoringSnapshotResponseApi>((resolve) => {
                          resolveOldSnapshot = resolve
                      })
                    : Promise.resolve(snapshot({ organizationId: `org-${teamId}` })))
        )
        mockSeriesRetrieve.mockImplementation(
            async (teamId, { metric }) =>
                await (teamId === String(MOCK_TEAM_ID)
                    ? new Promise<ManagedWarehouseMonitoringSeriesResponseApi>((resolve) => {
                          oldSeriesResolvers.set(metric, resolve)
                      })
                    : Promise.resolve(seriesResponse(metric, `org-${teamId}`)))
        )
        mountLogic()
        await jest.advanceTimersByTimeAsync(0)

        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            id: 1234,
            project_id: 1234,
            organization: 'org-2',
        })
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values.monitoringSnapshot?.org_id).toBe('org-1234')

        resolveOldSnapshot?.(snapshot({ organizationId: `org-${MOCK_TEAM_ID}` }))
        for (const [metric, resolve] of oldSeriesResolvers) {
            resolve(seriesResponse(metric, `org-${MOCK_TEAM_ID}`))
        }
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.monitoringSnapshot?.org_id).toBe('org-1234')
        expect(logic.values.monitoringSeries).toHaveLength(8)
        expect(logic.values.monitoringSeries.every((response) => response.org_id === 'org-1234')).toBe(true)
    })

    it('ignores failures from requests superseded by a team change', async () => {
        silenceKeaLoadersErrors()
        let rejectOldSnapshot: ((reason: Error) => void) | undefined
        mockSnapshotRetrieve.mockImplementation(
            async (teamId) =>
                await (teamId === String(MOCK_TEAM_ID)
                    ? new Promise<ManagedWarehouseMonitoringSnapshotResponseApi>((_, reject) => {
                          rejectOldSnapshot = reject
                      })
                    : Promise.resolve(snapshot({ organizationId: `org-${teamId}` })))
        )
        mountLogic()
        await jest.advanceTimersByTimeAsync(0)

        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            id: 1234,
            project_id: 1234,
            organization: 'org-2',
        })
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values.monitoringSnapshot?.org_id).toBe('org-1234')
        expect(logic.values.monitoringSnapshotError).toBe(false)

        rejectOldSnapshot?.(new Error('old organization unavailable'))
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.monitoringSnapshot?.org_id).toBe('org-1234')
        expect(logic.values.monitoringSnapshotError).toBe(false)
        expect(logic.values.monitoringSnapshotLoading).toBe(false)
    })
})
