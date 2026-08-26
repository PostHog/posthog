import { BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import {
    buildSpendTrackingProperties,
    filterSpendUsageTypes,
    getSpendTypeOptions,
    getUsageTypeOptions,
    isAddonVisible,
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

describe('isAddonVisible', () => {
    it('keeps an addon visible even when a billing_hide_addon flag is set', () => {
        // The generic hide-flag mechanism was removed. A stray hide flag must no longer suppress an addon.
        const product = { type: 'product_analytics' } as BillingProductV2Type
        const addon = { type: 'group_analytics', inclusion_only: false } as BillingProductV2AddonType
        expect(isAddonVisible(product, addon, { billing_hide_addon_group_analytics: true })).toBe(true)
    })
})
