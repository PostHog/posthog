import { billingJson } from '~/mocks/fixtures/_billing'
import { BillingProductV2Type } from '~/types'

import { getHeldCompanions, isCompanionHeld, isCompanionProduct } from './billing-utils'

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
