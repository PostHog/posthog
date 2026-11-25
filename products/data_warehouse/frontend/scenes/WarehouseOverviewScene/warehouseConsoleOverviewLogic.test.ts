import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    dataWarehouseManagedWarehouseTrinoMonitoringRetrieve,
    managedWarehouseConsoleUsageRetrieve,
} from 'products/data_warehouse/frontend/generated/api'
import type {
    ManagedWarehouseTrinoMonitoringSnapshotResponseApi,
    UsageSummaryApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import { GIB, TIB } from '../WarehouseConsole/warehouseConsoleFormat'
import { warehouseConsoleOverviewLogic, workloadCounts } from './warehouseConsoleOverviewLogic'

jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    managedWarehouseConsoleUsageRetrieve: jest.fn(),
    dataWarehouseManagedWarehouseTrinoMonitoringRetrieve: jest.fn(),
}))

const mockUsage = managedWarehouseConsoleUsageRetrieve as jest.MockedFunction<
    typeof managedWarehouseConsoleUsageRetrieve
>
const mockWorkload = dataWarehouseManagedWarehouseTrinoMonitoringRetrieve as jest.MockedFunction<
    typeof dataWarehouseManagedWarehouseTrinoMonitoringRetrieve
>

const USAGE: UsageSummaryApi = {
    period_start: '2026-11-01',
    period_end: '2026-12-01',
    compute: {
        billable_bytes: 5 * TIB,
        failed_billable_bytes: 0,
        logical_bytes: 5 * TIB,
        queries: 10,
        free_bytes: 4 * TIB,
        estimated_cost_usd: '6.250000',
    },
    storage: {
        gib_months: '50.000000',
        average_bytes: 50 * GIB,
        free_gib_months: '100.000000',
        estimated_cost_usd: '0',
    },
    total_estimated_cost_usd: '6.25',
    forecast_total_usd: null,
    daily: [],
    breakdown: [],
    budget: { monthly_budget_usd: null, share_used: null },
}

function snapshot(
    available: boolean,
    running: number,
    queued: number
): ManagedWarehouseTrinoMonitoringSnapshotResponseApi {
    return { available, totals: { running, queued } } as ManagedWarehouseTrinoMonitoringSnapshotResponseApi
}

describe('warehouseConsoleOverviewLogic', () => {
    let logic: ReturnType<typeof warehouseConsoleOverviewLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        mockUsage.mockResolvedValue(USAGE)
        mockWorkload.mockResolvedValue(snapshot(true, 2, 1))
        logic = warehouseConsoleOverviewLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('derives the compute and storage meters from this month usage', async () => {
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockUsage).toHaveBeenCalledWith(expect.any(String), { period: 'current_month' })
        expect(logic.values.computeMeter).toMatchObject({ used: 5 * TIB, free: 4 * TIB, overFree: true })
        expect(logic.values.storageMeter).toMatchObject({ used: 50, free: 100, overFree: false })
        expect(logic.values.workload).toEqual({ running: 2, queued: 1 })
    })

    it('reloads usage and the workload on retry after a failed load', async () => {
        mockUsage.mockRejectedValueOnce(new Error('nope'))
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.overviewFailed).toBe(true)
        expect(logic.values.overviewUsage).toBeNull()

        logic.actions.retryOverview()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.overviewFailed).toBe(false)
        expect(logic.values.overviewUsage).toEqual(USAGE)
        expect(mockWorkload).toHaveBeenCalledTimes(2)
    })
})

describe('workloadCounts', () => {
    it.each([
        ['no snapshot yet', null, null],
        ['live data unavailable, where zero totals do not mean idle', snapshot(false, 0, 0), null],
        ['live data available', snapshot(true, 3, 4), { running: 3, queued: 4 }],
    ])('with %s', (_name, input, expected) => {
        expect(workloadCounts(input)).toEqual(expected)
    })
})
