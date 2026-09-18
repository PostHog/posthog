import {
    billingErrorGuidance,
    buildSpendTrackingProperties,
    filterSpendUsageTypes,
    getSpendTypeOptions,
    getUsageTypeOptions,
    usageByProjectUrl,
} from './billing-utils'
import { REPLAY_VISION_USAGE_TYPE } from './constants'

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

describe('usageByProjectUrl', () => {
    it('lands on the usage tab already filtered to the type and split by project', () => {
        const url = usageByProjectUrl(REPLAY_VISION_USAGE_TYPE)

        expect(url).not.toBeNull()
        const params = new URLSearchParams((url as string).split('?')[1])
        expect(JSON.parse(params.get('usage_types') as string)).toEqual([REPLAY_VISION_USAGE_TYPE])
        expect(JSON.parse(params.get('breakdowns') as string)).toContain('team')
    })

    it('offers no link for a type the usage tab cannot filter by', () => {
        // A product's `usage_key` names a billing limit, so it never works as a usage type.
        expect(usageByProjectUrl('recordings')).toBeNull()
        expect(usageByProjectUrl('made_up_usage_type')).toBeNull()
    })

    it('still splits by project when no type is named', () => {
        const url = usageByProjectUrl()

        const params = new URLSearchParams((url as string).split('?')[1])
        expect(params.get('usage_types')).toBeNull()
        expect(JSON.parse(params.get('breakdowns') as string)).toContain('team')
    })
})
