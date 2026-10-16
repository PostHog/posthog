import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { TimeSeriesLineChart } from '@posthog/quill-charts'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import {
    dataWarehouseManagedWarehouseMonitoringRetrieve,
    dataWarehouseManagedWarehouseMonitoringTimeseriesRetrieve,
} from 'products/data_warehouse/frontend/generated/api'
import type {
    ManagedWarehouseMonitoringSeriesResponseApi,
    ManagedWarehouseMonitoringSnapshotResponseApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import { managedWarehouseMonitoringLogic } from './managedWarehouseMonitoringLogic'
import { MonitoringTab } from './MonitoringTab'

jest.mock('@posthog/quill-charts', () => ({
    ...jest.requireActual('@posthog/quill-charts'),
    TimeSeriesLineChart: jest.fn(({ series }: { series: Array<{ key: string }> }) => (
        <div data-testid="monitoring-chart">{series.map(({ key }) => key).join(',')}</div>
    )),
}))

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
const mockTimeSeriesLineChart = jest.mocked(TimeSeriesLineChart)

const monitoringSnapshot: ManagedWarehouseMonitoringSnapshotResponseApi = {
    schema_version: 1,
    org_id: 'org-1',
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
        workers: 0,
        allocated_cpu_cores: 0,
        allocated_memory_bytes: 0,
        active_sessions: 0,
        running_queries: 0,
        queued_connections: 0,
    },
    workers: [],
    coverage: { cp_responders: 1, cp_total: 1, partial: false },
}

function seriesResponse(
    metric: ManagedWarehouseMonitoringSeriesResponseApi['metric']
): ManagedWarehouseMonitoringSeriesResponseApi {
    return {
        schema_version: 1,
        org_id: 'org-1',
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

describe('MonitoringTab', () => {
    let logic: ReturnType<typeof managedWarehouseMonitoringLogic.build>

    beforeEach(() => {
        initKeaTests()
        silenceKeaLoadersErrors()
        mockSnapshotRetrieve.mockReset()
        mockSeriesRetrieve.mockReset()
        mockTimeSeriesLineChart.mockClear()
        mockSnapshotRetrieve.mockResolvedValue(monitoringSnapshot)
        mockSeriesRetrieve.mockRejectedValue(new Error('series unavailable'))
        logic = managedWarehouseMonitoringLogic()
    })

    afterEach(() => {
        cleanup()
        resumeKeaLoadersErrors()
    })

    it('keeps settled empty charts mounted while another time range loads', async () => {
        render(
            <Provider>
                <MonitoringTab />
            </Provider>
        )

        await screen.findByText("Historical metrics couldn't be loaded. Refresh to try again.")
        expect(screen.queryByText('Data read rate')).not.toBeInTheDocument()
        expect(screen.getByText('Tracked storage')).toBeInTheDocument()
        const settledEmptyCharts = screen.getAllByText('No data in this time range.')
        expect(settledEmptyCharts).toHaveLength(7)

        const resolveRequests: Array<() => void> = []
        mockSeriesRetrieve.mockImplementation(
            async (_teamId, { metric }) =>
                await new Promise<ManagedWarehouseMonitoringSeriesResponseApi>((resolve) => {
                    resolveRequests.push(() => resolve({ ...seriesResponse(metric), series: [] }))
                })
        )

        act(() => logic.actions.setMonitoringWindow('7d'))
        await waitFor(() => expect(logic.values.monitoringSeriesLoading).toBe(true))

        const emptyChartsWhileLoading = screen.getAllByText('No data in this time range.')
        expect(emptyChartsWhileLoading).toHaveLength(settledEmptyCharts.length)
        emptyChartsWhileLoading.forEach((chart, index) => expect(chart).toBe(settledEmptyCharts[index]))
        expect(screen.getByText("Historical metrics couldn't be loaded. Refresh to try again.")).toBeInTheDocument()

        await act(async () => {
            for (const resolveRequest of resolveRequests) {
                resolveRequest()
            }
        })
        await waitFor(() => expect(logic.values.monitoringSeriesLoading).toBe(false))
    })

    it('does not redraw populated charts for an in-flight time range', async () => {
        mockSeriesRetrieve.mockImplementation(async (_teamId, { metric }) => seriesResponse(metric))
        render(
            <Provider>
                <MonitoringTab />
            </Provider>
        )

        await waitFor(() => expect(mockTimeSeriesLineChart).toHaveBeenCalledTimes(7))
        mockTimeSeriesLineChart.mockClear()

        const resolveRequests: Array<() => void> = []
        mockSeriesRetrieve.mockImplementation(
            async (_teamId, { metric }) =>
                await new Promise<ManagedWarehouseMonitoringSeriesResponseApi>((resolve) => {
                    resolveRequests.push(() => resolve(seriesResponse(metric)))
                })
        )

        act(() => logic.actions.setMonitoringWindow('7d'))
        await waitFor(() => expect(logic.values.monitoringSeriesLoading).toBe(true))

        expect(mockTimeSeriesLineChart).not.toHaveBeenCalled()

        await act(async () => {
            for (const resolveRequest of resolveRequests) {
                resolveRequest()
            }
        })
        await waitFor(() => expect(logic.values.monitoringSeriesLoading).toBe(false))
        expect(mockTimeSeriesLineChart).toHaveBeenCalledTimes(7)
    })
})
