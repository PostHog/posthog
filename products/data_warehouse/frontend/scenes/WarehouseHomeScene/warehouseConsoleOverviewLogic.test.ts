import type { ConsoleSettingsApi, UsageSummaryApi } from '../../generated/api.schemas'
import { GIB, TIB } from '../WarehouseConsole/warehouseConsoleFormat'
import { buildRecommendations, topConsumers } from './warehouseConsoleOverviewLogic'

function usage(
    overrides: Partial<UsageSummaryApi> = {},
    compute: Partial<UsageSummaryApi['compute']> = {}
): UsageSummaryApi {
    return {
        period_start: '2026-11-01',
        period_end: '2026-12-01',
        compute: {
            billable_bytes: 1 * TIB,
            failed_billable_bytes: 0,
            logical_bytes: 1 * TIB,
            queries: 10,
            free_bytes: 4 * TIB,
            estimated_cost_usd: '0',
            ...compute,
        },
        storage: { gib_months: '10', average_bytes: 10 * GIB, free_gib_months: '100', estimated_cost_usd: '0' },
        total_estimated_cost_usd: '0',
        forecast_total_usd: '5.00',
        daily: [],
        breakdown: [
            { key: 'a', label: 'A', queries: 1, billable_bytes: 0.5 * TIB, estimated_cost_share_usd: '0' },
            { key: 'b', label: 'B', queries: 1, billable_bytes: 0.5 * TIB, estimated_cost_share_usd: '0' },
        ],
        budget: { monthly_budget_usd: '10.00', share_used: '0.1' },
        ...overrides,
    }
}

const FULL_SETTINGS: ConsoleSettingsApi = { max_scan_bytes_per_query: 10 * GIB, monthly_budget_usd: '10.00' }
const keys = (items: ReturnType<typeof buildRecommendations>): string[] => items.map((item) => item.key)

describe('buildRecommendations', () => {
    it('suggests nothing when limits are set and usage is healthy', () => {
        expect(buildRecommendations(usage(), FULL_SETTINGS, true)).toEqual([])
    })

    it.each([
        ['an admin without limits', true, ['set_budget', 'set_scan_cap']],
        ['a member without limits', false, []],
    ])('handles %s', (_name, isAdmin, expected) => {
        const settings = { max_scan_bytes_per_query: null, monthly_budget_usd: null }
        expect(
            keys(
                buildRecommendations(
                    usage({ budget: { monthly_budget_usd: null, share_used: null } }),
                    settings,
                    isAdmin
                )
            )
        ).toEqual(expected)
    })

    it('flags a forecast above the budget only when both exist', () => {
        expect(keys(buildRecommendations(usage({ forecast_total_usd: '12.00' }), FULL_SETTINGS, false))).toEqual([
            'forecast_over_budget',
        ])
        expect(keys(buildRecommendations(usage({ forecast_total_usd: '10.00' }), FULL_SETTINGS, false))).toEqual([])
        expect(keys(buildRecommendations(usage({ forecast_total_usd: null }), FULL_SETTINGS, false))).toEqual([])
    })

    it('links a high failed share to the failed queries filter', () => {
        const items = buildRecommendations(usage({}, { failed_billable_bytes: 0.2 * TIB }), FULL_SETTINGS, false)
        expect(items).toHaveLength(1)
        expect(items[0].to).toContain('?status=failed')
        expect(
            keys(buildRecommendations(usage({}, { failed_billable_bytes: 0.1 * TIB }), FULL_SETTINGS, false))
        ).toEqual([])
    })

    it('flags one login above half of the data only past the free allowance', () => {
        const dominant = [
            { key: 'a', label: 'A', queries: 1, billable_bytes: 4 * TIB, estimated_cost_share_usd: '1' },
            { key: 'b', label: 'B', queries: 1, billable_bytes: 1 * TIB, estimated_cost_share_usd: '0' },
        ]
        const past = usage({ breakdown: dominant }, { billable_bytes: 5 * TIB })
        expect(keys(buildRecommendations(past, FULL_SETTINGS, false))).toEqual(['dominant_login'])
        const within = usage({ breakdown: dominant }, { billable_bytes: 3.9 * TIB })
        expect(keys(buildRecommendations(within, FULL_SETTINGS, false))).toEqual([])
    })
})

describe('topConsumers', () => {
    it('drops the Other row, sorts by bytes and keeps five', () => {
        const rows = [1, 2, 3, 4, 5, 6].map((n) => ({
            key: `k${n}`,
            label: `L${n}`,
            queries: n,
            billable_bytes: n * GIB,
            estimated_cost_share_usd: '0',
        }))
        rows.push({
            key: 'other',
            label: 'Other',
            queries: 1,
            billable_bytes: 100 * GIB,
            estimated_cost_share_usd: '0',
        })
        expect(topConsumers(rows).map((row) => row.label)).toEqual(['L6', 'L5', 'L4', 'L3', 'L2'])
    })
})
