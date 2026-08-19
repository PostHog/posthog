import { ApiError } from 'lib/api-error'

import {
    buildSpendTrackingProperties,
    filterSpendUsageTypes,
    getBillingErrorMessage,
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

describe('getBillingErrorMessage', () => {
    it('surfaces the billing service detail so a limit message reads as a limit message', () => {
        const error = new ApiError('failed', 400, undefined, {
            detail: 'You have reached your project breakdown limit.',
            code: 'breakdown_limit_reached',
        })
        expect(getBillingErrorMessage(error, 'fallback')).toBe('You have reached your project breakdown limit.')
    })

    it('falls back when the error carries no detail', () => {
        const error = new ApiError('failed', 500, undefined, {})
        expect(getBillingErrorMessage(error, 'fallback')).toBe('fallback')
        expect(getBillingErrorMessage(new Error('boom'), 'fallback')).toBe('fallback')
    })
})
