import { BillingProductV2Type } from '~/types'

import {
    buildSpendTrackingProperties,
    createGaugeItems,
    filterSpendUsageTypes,
    getSpendTypeOptions,
    getUsageTypeOptions,
} from './billing-utils'
import { BillingGaugeItemKind } from './types'

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

describe('createGaugeItems', () => {
    const baseProduct = { type: 'product_analytics', projected_usage: 5000 } as BillingProductV2Type

    it('marks current usage unavailable when the billing service returns no usage', () => {
        // Regression: a missing current_usage used to fall back to a confident 0, disagreeing with the tier table.
        const items = createGaugeItems({ ...baseProduct, current_usage: undefined })
        const current = items.find((item) => item.type === BillingGaugeItemKind.CurrentUsage)
        expect(current).toMatchObject({ value: 0, unavailable: true })
        // A projection off an unknown current usage would be just as misleading, so it is dropped too.
        expect(items.some((item) => item.type === BillingGaugeItemKind.ProjectedUsage)).toBe(false)
    })

    it('keeps a real zero as a known value', () => {
        const items = createGaugeItems({ ...baseProduct, current_usage: 0 })
        const current = items.find((item) => item.type === BillingGaugeItemKind.CurrentUsage)
        expect(current).toMatchObject({ value: 0, unavailable: false })
        expect(items.some((item) => item.type === BillingGaugeItemKind.ProjectedUsage)).toBe(true)
    })
})
