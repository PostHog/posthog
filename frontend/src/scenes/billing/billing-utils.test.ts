import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { BillingProductV2Type } from '~/types'

import {
    billingErrorGuidance,
    buildSpendTrackingProperties,
    createGaugeItems,
    filterSpendUsageTypes,
    getSpendTypeOptions,
    getUsageTypeOptions,
} from './billing-utils'
import { BillingGaugeItemKind } from './types'

describe('getUsageTypeOptions', () => {
    it('includes informational Desktop component metrics in Usage but not Spend', () => {
        const featureFlags = { [FEATURE_FLAGS.CLOUD_AGENTS]: true }
        const usageOptions = getUsageTypeOptions(featureFlags)
        const spendOptions = getSpendTypeOptions(featureFlags)
        const componentTypes = [
            'posthog_code_token_credits_used_in_period',
            'sandbox_compute_credits_used_in_period',
            'sandbox_compute_cpu_millicore_seconds_in_period',
            'sandbox_compute_memory_mib_seconds_in_period',
            'cloud_agents_token_credits_used_in_period',
            'cloud_agents_compute_credits_used_in_period',
        ]

        for (const usageType of componentTypes) {
            expect(usageOptions.some((option) => option.key === usageType)).toBe(true)
            expect(spendOptions.some((option) => option.key === usageType)).toBe(false)
        }
    })

    it.each<{ case: string; featureFlags: FeatureFlagsSet; offered: boolean }>([
        { case: 'the flag is on', featureFlags: { [FEATURE_FLAGS.CLOUD_AGENTS]: true }, offered: true },
        { case: 'the flag is off', featureFlags: { [FEATURE_FLAGS.CLOUD_AGENTS]: false }, offered: false },
        { case: 'the flag is not present', featureFlags: {}, offered: false },
    ])('offers the Cloud agents types only behind their flag when $case', ({ featureFlags, offered }) => {
        const usageKeys = getUsageTypeOptions(featureFlags).map((option) => option.key)
        const spendKeys = getSpendTypeOptions(featureFlags).map((option) => option.key)

        expect(spendKeys.includes('cloud_agents_credits_used_in_period')).toBe(offered)
        for (const usageType of [
            'cloud_agents_credits_used_in_period',
            'cloud_agents_token_credits_used_in_period',
            'cloud_agents_compute_credits_used_in_period',
        ]) {
            expect(usageKeys.includes(usageType)).toBe(offered)
        }
        expect(usageKeys).toContain('event_count_in_period')
        expect(spendKeys).toContain('event_count_in_period')
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

describe('createGaugeItems', () => {
    const productAnalytics = billingJson.products.find((p) => p.type === 'product_analytics') as BillingProductV2Type

    it.each([
        ['draws the billing limit marker for a product that allows a limit', undefined, true],
        ['draws no billing limit marker for a product without billing limits', true, false],
    ])('%s', (_name, noBillingLimit, expectMarker) => {
        const product: BillingProductV2Type = { ...productAnalytics, no_billing_limit: noBillingLimit }

        const kinds = createGaugeItems(product, { billingLimitAsUsage: 1000000 }).map((item) => item.type)

        expect(kinds.includes(BillingGaugeItemKind.BillingLimit)).toBe(expectMarker)
    })
})
