import {
    buildSpendTrackingProperties,
    filterSpendUsageTypes,
    getSpendTypeOptions,
    getUsageTypeOptions,
    isUsageAlertDismissedForBand,
    usageAlertBand,
} from './billing-utils'

describe('getUsageTypeOptions', () => {
    it('includes informational Desktop component metrics in Usage but not Spend', () => {
        const usageOptions = getUsageTypeOptions()
        const spendOptions = getSpendTypeOptions()
        const componentTypes = [
            'posthog_code_token_credits_used_in_period',
            'sandbox_compute_credits_used_in_period',
            'sandbox_compute_cpu_millicore_seconds_in_period',
            'sandbox_compute_memory_mib_seconds_in_period',
        ]

        for (const usageType of componentTypes) {
            expect(usageOptions.some((option) => option.key === usageType)).toBe(true)
            expect(spendOptions.some((option) => option.key === usageType)).toBe(false)
        }
    })

    it('reports only selectable Spend types in interaction analytics', () => {
        const properties = buildSpendTrackingProperties('filters_changed', {
            filters: {},
            dateFrom: '2026-08-01',
            dateTo: '2026-08-06',
            excludeEmptySeries: false,
            teamOptions: [],
        })

        expect(properties.usage_types_total).toBe(getSpendTypeOptions().length)
    })

    it('removes Usage-only types when switching to Spend', () => {
        expect(
            filterSpendUsageTypes([
                'posthog_code_token_credits_used_in_period',
                'sandbox_compute_credits_used_in_period',
                'event_count_in_period',
            ])
        ).toEqual(['event_count_in_period'])
        expect(filterSpendUsageTypes(['sandbox_compute_cpu_millicore_seconds_in_period'])).toEqual([])
    })
})

describe('usageAlertBand', () => {
    it.each([
        [0.5, 0],
        [0.8, 0],
        [0.85, 1],
        [1, 1],
        [1.01, 2],
        [1.2, 2],
        [1.25, 3],
        [3, 3],
    ])('maps %p usage to band %p', (percentageUsage, expectedBand) => {
        expect(usageAlertBand(percentageUsage)).toBe(expectedBand)
    })
})

describe('isUsageAlertDismissedForBand', () => {
    const period = '2026-08-31'

    it('re-shows when nothing was dismissed', () => {
        expect(isUsageAlertDismissedForBand(null, period, 2)).toBe(false)
    })

    it('keeps hiding while the usage band has not increased', () => {
        expect(isUsageAlertDismissedForBand(`${period}:2`, period, 2)).toBe(true)
    })

    it('re-shows when usage crosses into a higher band', () => {
        // Dismissed at 100% (band 2), now over 120% (band 3).
        expect(isUsageAlertDismissedForBand(`${period}:2`, period, 3)).toBe(false)
    })

    it('re-shows when the billing period rolls over', () => {
        expect(isUsageAlertDismissedForBand('2026-07-31:3', period, 2)).toBe(false)
    })

    it('re-shows a legacy dismissal that carries no band', () => {
        expect(isUsageAlertDismissedForBand(period, period, 1)).toBe(false)
    })
})
