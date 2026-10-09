import { billingJson } from '~/mocks/fixtures/_billing'
import { BillingProductV2Type } from '~/types'

import {
    billingErrorGuidance,
    buildSpendTrackingProperties,
    createGaugeItems,
    filterSpendUsageTypes,
    getHeldCompanions,
    getSpendTypeOptions,
    getUsageTypeOptions,
    isCompanionHeld,
    isCompanionProduct,
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

describe('companion products', () => {
    const productAnalytics = billingJson.products.find((p) => p.type === 'product_analytics') as BillingProductV2Type
    const plansWithCurrent = (current: boolean): BillingProductV2Type['plans'] =>
        productAnalytics.plans.map((plan) => ({ ...plan, current_plan: current }))
    const companion = (
        type: string,
        companionOf: string,
        state: { subscribed: boolean; onCurrentPlan: boolean }
    ): BillingProductV2Type => ({
        ...productAnalytics,
        type,
        companion_of: companionOf,
        inclusion_only: true,
        no_billing_limit: true,
        addons: [],
        usage_limit: null,
        subscribed: state.subscribed,
        plans: plansWithCurrent(state.onCurrentPlan),
    })

    it.each([
        ['a companion', 'logs', true],
        ['a product without companion_of', undefined, false],
        ['a product with a null companion_of', null, false],
    ])('isCompanionProduct recognizes %s', (_name, companionOf, expected) => {
        expect(isCompanionProduct({ ...productAnalytics, companion_of: companionOf })).toBe(expected)
    })

    it.each([
        ['a subscribed companion', { subscribed: true, onCurrentPlan: false }, true],
        ['an unsubscribed companion still on its plan', { subscribed: false, onCurrentPlan: true }, true],
        ['a companion the customer does not hold', { subscribed: false, onCurrentPlan: false }, false],
    ])('isCompanionHeld counts %s', (_name, state, expected) => {
        expect(isCompanionHeld(companion('logs_retention_custom', 'logs', state))).toBe(expected)
    })

    it('getHeldCompanions returns only the held companions of the given parent', () => {
        const held = companion('logs_retention_custom', 'logs', { subscribed: true, onCurrentPlan: true })
        const stale = companion('logs_extra', 'logs', { subscribed: false, onCurrentPlan: true })
        const notHeld = companion('logs_other', 'logs', { subscribed: false, onCurrentPlan: false })
        const otherParent = companion('replay_extra', 'session_replay', { subscribed: true, onCurrentPlan: true })

        expect(
            getHeldCompanions([productAnalytics, held, stale, notHeld, otherParent], 'logs').map((p) => p.type)
        ).toEqual(['logs_retention_custom', 'logs_extra'])
        expect(getHeldCompanions([productAnalytics, notHeld, otherParent], 'logs')).toEqual([])
        expect(getHeldCompanions(undefined, 'logs')).toEqual([])
    })
})
