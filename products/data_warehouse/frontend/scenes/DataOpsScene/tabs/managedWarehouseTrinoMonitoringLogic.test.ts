import { MOCK_TEAM_ID } from 'lib/api.mock'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import {
    dataWarehouseManagedWarehouseTrinoMonitoringRetrieve,
    dataWarehouseManagedWarehouseTrinoMonitoringTimeseriesRetrieve,
} from 'products/data_warehouse/frontend/generated/api'
import type {
    ManagedWarehouseMonitoringSeriesResponseApi,
    ManagedWarehouseTrinoMonitoringSnapshotResponseApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import { managedWarehouseTrinoMonitoringLogic } from './managedWarehouseTrinoMonitoringLogic'

jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    dataWarehouseManagedWarehouseTrinoMonitoringRetrieve: jest.fn(),
    dataWarehouseManagedWarehouseTrinoMonitoringTimeseriesRetrieve: jest.fn(),
}))

const mockSnapshotRetrieve = dataWarehouseManagedWarehouseTrinoMonitoringRetrieve as jest.MockedFunction<
    typeof dataWarehouseManagedWarehouseTrinoMonitoringRetrieve
>
const mockSeriesRetrieve = dataWarehouseManagedWarehouseTrinoMonitoringTimeseriesRetrieve as jest.MockedFunction<
    typeof dataWarehouseManagedWarehouseTrinoMonitoringTimeseriesRetrieve
>

function snapshot(inFlight = 0): ManagedWarehouseTrinoMonitoringSnapshotResponseApi {
    return {
        schema_version: 1,
        org_id: 'org-1',
        as_of: '2026-09-30T10:00:00Z',
        trino: { state: 'ready', ready_at: '2026-09-01T12:00:00Z', failed_at: null },
        available: true,
        limits: { max_running_queries: 10, max_queued_queries: 50 },
        totals: {
            in_flight: inFlight,
            running: inFlight,
            queued: 0,
            blocked: 0,
            longest_running_ms: 0,
            physical_input_bytes: 0,
        },
        queries: [],
        queries_truncated: false,
    }
}

function seriesResponse(metric: string): ManagedWarehouseMonitoringSeriesResponseApi {
    return {
        schema_version: 1,
        org_id: 'org-1',
        metric,
        unit: 'count',
        start: '2026-09-30T09:59:00Z',
        end: '2026-09-30T10:00:00Z',
        step_seconds: 60,
        series: [{ labels: {}, points: [{ timestamp: '2026-09-30T10:00:00Z', value: 1 }] }],
    }
}

describe('managedWarehouseTrinoMonitoringLogic', () => {
    let logic: ReturnType<typeof managedWarehouseTrinoMonitoringLogic.build>

    const mountLogic = (): void => {
        logic = managedWarehouseTrinoMonitoringLogic()
        logic.mount()
    }

    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        mockSnapshotRetrieve.mockReset()
        mockSeriesRetrieve.mockReset()
        mockSnapshotRetrieve.mockResolvedValue(snapshot())
        mockSeriesRetrieve.mockImplementation(async (_teamId, { metric }) => seriesResponse(metric))
    })

    afterEach(() => {
        logic?.unmount()
        resumeKeaLoadersErrors()
        jest.useRealTimers()
    })

    it('loads the live snapshot and every Trino series on mount', async () => {
        mountLogic()
        await jest.advanceTimersByTimeAsync(0)

        expect(mockSnapshotRetrieve).toHaveBeenCalledWith(String(MOCK_TEAM_ID))
        expect(mockSeriesRetrieve.mock.calls.map(([, { metric }]) => metric)).toEqual([
            'query_rate',
            'error_ratio',
            'duration_p50',
            'duration_p95',
            'queries_in_flight',
            'queue_time_p95',
            'scanned_bytes_rate',
            'cpu_seconds_rate',
            'storage_bytes',
        ])
        expect(mockSeriesRetrieve.mock.calls.every(([, params]) => params.window === '24h')).toBe(true)
        expect(logic.values.monitoringSeries).toHaveLength(9)
    })

    it.each([
        { name: 'queries in flight', inFlight: 1, intervalMs: 15_000 },
        { name: 'an idle warehouse', inFlight: 0, intervalMs: 60_000 },
    ])('polls the snapshot at the expected interval for $name', async ({ inFlight, intervalMs }) => {
        mockSnapshotRetrieve.mockResolvedValue(snapshot(inFlight))
        mountLogic()
        await jest.advanceTimersByTimeAsync(0)

        await jest.advanceTimersByTimeAsync(intervalMs - 1)
        expect(mockSnapshotRetrieve).toHaveBeenCalledTimes(1)

        await jest.advanceTimersByTimeAsync(1)
        expect(mockSnapshotRetrieve).toHaveBeenCalledTimes(2)
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
})
