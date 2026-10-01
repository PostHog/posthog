import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import {
    dataWarehouseManagedWarehouseTrinoMonitoringRetrieve,
    dataWarehouseManagedWarehouseTrinoMonitoringTimeseriesRetrieve,
} from 'products/data_warehouse/frontend/generated/api'
import type { ManagedWarehouseTrinoMonitoringSnapshotResponseApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { TrinoMonitoringTab } from './TrinoMonitoringTab'

jest.mock('@posthog/quill-charts', () => ({
    ...jest.requireActual('@posthog/quill-charts'),
    TimeSeriesLineChart: jest.fn(() => <div data-testid="monitoring-chart" />),
}))

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

const busySnapshot: ManagedWarehouseTrinoMonitoringSnapshotResponseApi = {
    schema_version: 1,
    org_id: 'org-1',
    as_of: '2026-09-30T10:00:00Z',
    trino: { state: 'ready', ready_at: '2026-09-01T12:00:00Z', failed_at: null },
    available: true,
    limits: { max_running_queries: 10, max_queued_queries: 50 },
    totals: {
        in_flight: 5,
        running: 3,
        queued: 2,
        blocked: 1,
        longest_running_ms: 400_000,
        physical_input_bytes: 2048,
    },
    queries: [
        {
            query_id: 'query-1',
            state: 'running',
            user: 'analyst',
            source: 'dbt',
            query: 'SELECT * FROM t WHERE email = ?',
            created_at: '2026-09-30T09:53:20Z',
            elapsed_ms: 400_000,
            queued_ms: 20,
            cpu_ms: 900,
            physical_input_bytes: 2048,
            peak_memory_bytes: 64,
            processed_input_rows: 7,
            progress_percentage: 50,
            blocked: true,
        },
    ],
    queries_truncated: true,
}

const unavailableSnapshot: ManagedWarehouseTrinoMonitoringSnapshotResponseApi = {
    ...busySnapshot,
    available: false,
    totals: { in_flight: 0, running: 0, queued: 0, blocked: 0, longest_running_ms: 0, physical_input_bytes: 0 },
    queries: [],
    queries_truncated: false,
}

describe('TrinoMonitoringTab', () => {
    const renderTab = (): void => {
        render(
            <Provider>
                <TrinoMonitoringTab />
            </Provider>
        )
    }

    beforeEach(() => {
        initKeaTests()
        silenceKeaLoadersErrors()
        mockSnapshotRetrieve.mockReset()
        mockSeriesRetrieve.mockReset()
        mockSeriesRetrieve.mockRejectedValue(new Error('series unavailable'))
    })

    afterEach(() => {
        cleanup()
        resumeKeaLoadersErrors()
    })

    it('shows live totals against their limits and the in-flight queries', async () => {
        mockSnapshotRetrieve.mockResolvedValue(busySnapshot)
        renderTab()

        expect(await screen.findByText('SELECT * FROM t WHERE email = ?')).toBeInTheDocument()
        expect(screen.getByText('3 / 10')).toBeInTheDocument()
        expect(screen.getByText('2 / 50')).toBeInTheDocument()
        expect(screen.getByText('analyst')).toBeInTheDocument()
        expect(screen.getByText('Long running')).toBeInTheDocument()
        expect(screen.getByText('Showing the 200 longest-running queries.')).toBeInTheDocument()
        expect(screen.queryByText(/worker/i)).not.toBeInTheDocument()
    })

    // Totals are zero when the coordinator cannot be read. Showing them would tell the user the
    // warehouse is idle during an outage.
    it('does not present an unavailable coordinator as an idle warehouse', async () => {
        mockSnapshotRetrieve.mockResolvedValue(unavailableSnapshot)
        renderTab()

        expect(
            await screen.findByText(
                'Live query data is temporarily unavailable. Historical charts may still be up to date.'
            )
        ).toBeInTheDocument()
        expect(screen.queryByText('No queries are running right now.')).not.toBeInTheDocument()
        expect(screen.queryByText('0 / 10')).not.toBeInTheDocument()
    })
})
