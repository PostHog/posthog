import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import {
    dataWarehouseWarehouseStatusRetrieve,
    managedWarehouseConsoleSettingsPartialUpdate,
    managedWarehouseConsoleSettingsRetrieve,
    managedWarehouseConsoleUsageRetrieve,
} from 'products/data_warehouse/frontend/generated/api'
import type { UsageSummaryApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { trinoStatusFixture, warehouseStatusFixture } from '../DataOpsScene/tabs/warehouseStatusFixtures'
import { GIB, TIB } from '../WarehouseConsole/warehouseConsoleFormat'
import {
    changedSettings,
    findFreeAllowanceCrossing,
    parseSpendControls,
    warehouseUsageLogic,
} from './warehouseUsageLogic'

jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    dataWarehouseWarehouseStatusRetrieve: jest.fn().mockResolvedValue(null),
    managedWarehouseConsoleUsageRetrieve: jest.fn(),
    managedWarehouseConsoleSettingsRetrieve: jest.fn(),
    managedWarehouseConsoleSettingsPartialUpdate: jest.fn(),
}))

function usage(overrides: Partial<UsageSummaryApi> = {}): UsageSummaryApi {
    return {
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
        daily: [
            { date: '2026-11-01', billable_bytes: 3 * TIB, queries: 4, storage_average_bytes: 0 },
            { date: '2026-11-02', billable_bytes: 2 * TIB, queries: 6, storage_average_bytes: 0 },
        ],
        breakdown: [
            { key: 'a', label: 'A', queries: 3, billable_bytes: 3 * TIB, estimated_cost_share_usd: '3.75' },
            { key: 'b', label: 'B', queries: 7, billable_bytes: 1 * TIB, estimated_cost_share_usd: '1.25' },
        ],
        budget: { monthly_budget_usd: '10.00', share_used: '0.625' },
        ...overrides,
    }
}

describe('warehouse usage', () => {
    describe('warehouseUsageLogic', () => {
        let logic: ReturnType<typeof warehouseUsageLogic.build>

        beforeEach(() => {
            initKeaTests()
            logic = warehouseUsageLogic()
            logic.mount()
        })

        it('computes the free tier meters and the day the allowance runs out', async () => {
            await expectLogic(logic, () => logic.actions.loadUsageSuccess(usage())).toMatchValues({
                computeMeter: { used: 5 * TIB, free: 4 * TIB, percent: 125, overFree: true },
                storageMeter: { used: 50, free: 100, percent: 50, overFree: false },
                budgetPercent: 62.5,
                freeAllowanceCrossingDate: '2026-11-02',
            })
        })

        it('shares the breakdown by billable bytes', async () => {
            await expectLogic(logic, () => logic.actions.loadUsageSuccess(usage())).toMatchValues({
                breakdownRows: [
                    expect.objectContaining({ key: 'a', shareOfBytes: 0.75 }),
                    expect.objectContaining({ key: 'b', shareOfBytes: 0.25 }),
                ],
            })
        })

        it('shows the saved limits until the user edits them', () => {
            logic.actions.loadSettingsSuccess({ max_scan_bytes_per_query: 10 * GIB, monthly_budget_usd: '25.00' })
            expect(logic.values.budgetInput).toBe('25.00')
            expect(logic.values.scanCapInput).toBe('10')
            expect(logic.values.spendControlsDirty).toBe(false)

            logic.actions.setBudgetInput('30')
            expect(logic.values.spendControlsDirty).toBe(true)
            logic.actions.resetSpendControls()
            expect(logic.values.budgetInput).toBe('25.00')
        })
    })

    describe('warehouseUsageLogic loading and saving', () => {
        beforeEach(() => {
            jest.clearAllMocks()
            initKeaTests()
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE]: true })
        })

        it('loads the settings too when a URL grouping arrives before the warehouse status', async () => {
            ;(dataWarehouseWarehouseStatusRetrieve as jest.Mock).mockResolvedValue(
                warehouseStatusFixture({ trino: trinoStatusFixture() })
            )
            ;(managedWarehouseConsoleUsageRetrieve as jest.Mock).mockResolvedValue(usage())
            ;(managedWarehouseConsoleSettingsRetrieve as jest.Mock).mockResolvedValue({
                max_scan_bytes_per_query: null,
                monthly_budget_usd: '25.00',
            })
            const logic = warehouseUsageLogic()
            logic.mount()
            logic.actions.setGroupBy('principal')

            await expectLogic(logic).toDispatchActions([
                'loadWarehouseStatusSuccess',
                'loadUsageSuccess',
                'loadSettingsSuccess',
            ])
            expect(managedWarehouseConsoleUsageRetrieve).toHaveBeenCalledTimes(1)
            expect(managedWarehouseConsoleUsageRetrieve).toHaveBeenCalledWith(expect.any(String), {
                period: 'current_month',
                group_by: 'principal',
            })
            expect(logic.values.settings?.monthly_budget_usd).toBe('25.00')
        })

        it('saves only the limit that changed', async () => {
            const logic = warehouseUsageLogic()
            logic.mount()
            logic.actions.loadSettingsSuccess({ max_scan_bytes_per_query: null, monthly_budget_usd: '25.00' })
            ;(managedWarehouseConsoleSettingsPartialUpdate as jest.Mock).mockResolvedValue({
                max_scan_bytes_per_query: 20 * GIB,
                monthly_budget_usd: '25.00',
            })

            logic.actions.setScanCapInput('20')
            await expectLogic(logic, () => logic.actions.saveSpendControls()).toDispatchActions([
                'saveSpendControlsSuccess',
            ])
            expect(managedWarehouseConsoleSettingsPartialUpdate).toHaveBeenCalledWith(expect.any(String), {
                max_scan_bytes_per_query: 20 * GIB,
            })
        })
    })

    describe('changedSettings', () => {
        it.each([
            ['nothing changed', { monthly_budget_usd: '25.00', max_scan_bytes_per_query: GIB }, {}],
            ['a budget written differently', { monthly_budget_usd: '25', max_scan_bytes_per_query: GIB }, {}],
            [
                'a cleared budget',
                { monthly_budget_usd: null, max_scan_bytes_per_query: GIB },
                { monthly_budget_usd: null },
            ],
        ])('%s', (_name, payload, expected) => {
            expect(changedSettings(payload, { monthly_budget_usd: '25.00', max_scan_bytes_per_query: GIB })).toEqual(
                expected
            )
        })
    })

    describe('findFreeAllowanceCrossing', () => {
        it('returns null while the running total stays within the allowance', () => {
            expect(findFreeAllowanceCrossing(usage().daily, 6 * TIB)).toBeNull()
        })
    })

    describe('parseSpendControls', () => {
        it.each([
            ['empty inputs remove both limits', '', '', { monthly_budget_usd: null, max_scan_bytes_per_query: null }],
            [
                'valid inputs convert GiB to bytes',
                '12.5',
                '2',
                { monthly_budget_usd: '12.50', max_scan_bytes_per_query: 2 * GIB },
            ],
        ])('%s', (_name, budget, cap, payload) => {
            expect(parseSpendControls(budget, cap)).toEqual({ payload })
        })

        it.each([
            ['a budget with three decimals', '1.234', '', 'budget'],
            ['a budget that is not a number', 'lots', '', 'budget'],
            ['a cap below the 1 GiB minimum', '', '0.5', 'scanCap'],
            ['a cap in exponent notation', '', '1e3', 'scanCap'],
            ['a cap in hex', '', '0x10', 'scanCap'],
        ])('rejects %s', (_name, budget, cap, field) => {
            expect(parseSpendControls(budget, cap)).toMatchObject({ field })
        })
    })
})
