import {
    billingErrorGuidance,
    buildSpendTrackingProperties,
    filterSpendUsageTypes,
    getSpendTypeOptions,
    getUsageTypeOptions,
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

describe('billingErrorGuidance', () => {
    it('says what the page can do, in its own words, for the codes it knows', () => {
        expect(billingErrorGuidance({ code: 'usage_query_timeout', detail: 'api text' })).toMatch(/took too long/)
        expect(billingErrorGuidance({ code: 'usage_breakdown_too_large', detail: 'api text' })).toMatch(
            /too large to show/
        )
    })

    it('never tells a person to ask for pages, which is advice for an API caller', () => {
        for (const code of ['usage_query_timeout', 'usage_breakdown_too_large']) {
            expect(billingErrorGuidance({ code, detail: 'Ask for it a page at a time' })).not.toMatch(/page at a time/)
        }
    })

    it('falls back to billing text for a code it does not know', () => {
        expect(billingErrorGuidance({ code: 'something_new', detail: 'billing said this' })).toBe('billing said this')
    })
})
