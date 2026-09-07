import { creditsPerPr, findInboxProduct, freePrs, pricePerPrUsd } from 'scenes/billing/inboxPricing'

import { BillingPlanType, BillingProductV2Type, BillingTierType } from '~/types'

/** 1500 credits to a PR, matching the inbox product's `display_divisor`. */
const CREDITS_PER_PR = 1500

const tier = (unitAmountUsd: string): BillingTierType =>
    ({ unit_amount_usd: unitAmountUsd, up_to: null }) as BillingTierType

const plan = (overrides: Partial<BillingPlanType>): BillingPlanType =>
    ({ flat_rate: false, unit_amount_usd: null, tiers: null, ...overrides }) as BillingPlanType

const inbox = (overrides: Partial<BillingProductV2Type> = {}): BillingProductV2Type =>
    ({
        type: 'inbox',
        name: 'Inbox',
        display_divisor: CREDITS_PER_PR,
        free_allocation: 4500,
        subscribed: false,
        tiers: null,
        unit_amount_usd: null,
        plans: [],
        ...overrides,
    }) as BillingProductV2Type

describe('inboxPricing', () => {
    describe('findInboxProduct', () => {
        it('matches on product type', () => {
            const product = inbox()
            expect(findInboxProduct([{ type: 'product_analytics' } as BillingProductV2Type, product])).toBe(product)
        })

        it('returns null when billing has no inbox product', () => {
            expect(findInboxProduct([{ type: 'product_analytics' } as BillingProductV2Type])).toBeNull()
            expect(findInboxProduct(undefined)).toBeNull()
        })
    })

    describe('creditsPerPr', () => {
        it('is the display divisor', () => {
            expect(creditsPerPr(inbox())).toBe(CREDITS_PER_PR)
        })

        // Without a divisor we cannot convert credits to PRs, and a wrong conversion is worse than
        // no number at all.
        it('is null without a usable divisor', () => {
            expect(creditsPerPr(inbox({ display_divisor: undefined }))).toBeNull()
            expect(creditsPerPr(inbox({ display_divisor: 0 }))).toBeNull()
            expect(creditsPerPr(null)).toBeNull()
        })
    })

    describe('pricePerPrUsd', () => {
        it('scales the first paid tier on a subscribed product', () => {
            expect(pricePerPrUsd(inbox({ subscribed: true, tiers: [tier('0'), tier('0.01')] }))).toBe(15)
        })

        // The whole reason for the plan fallback: an unsubscribed customer sits on the free plan,
        // which has no Stripe price, so the product carries no tiers and no unit amount. Without
        // this the price silently disappears for exactly the users being asked to pick a plan.
        it('falls back to the paid plan when the product has no price', () => {
            const product = inbox({
                plans: [
                    plan({ plan_key: 'free-20260617', free_allocation: 4500 }),
                    plan({ plan_key: 'paid-20260617', tiers: [tier('0.01')] }),
                ],
            })
            expect(pricePerPrUsd(product)).toBe(15)
        })

        it('prefers the product price over the plan fallback', () => {
            const product = inbox({
                subscribed: true,
                tiers: [tier('0.02')],
                plans: [plan({ plan_key: 'paid-20260617', tiers: [tier('0.01')] })],
            })
            expect(pricePerPrUsd(product)).toBe(30)
        })

        it('uses the unit amount when there are no tiers', () => {
            expect(pricePerPrUsd(inbox({ unit_amount_usd: '0.01' }))).toBe(15)
        })

        it('is null when no plan carries a price', () => {
            expect(pricePerPrUsd(inbox({ plans: [plan({ plan_key: 'free-20260617' })] }))).toBeNull()
            expect(pricePerPrUsd(inbox({ display_divisor: undefined, tiers: [tier('0.01')] }))).toBeNull()
            expect(pricePerPrUsd(null)).toBeNull()
        })
    })

    describe('freePrs', () => {
        it('converts the free allocation to whole PRs', () => {
            expect(freePrs(inbox())).toBe(3)
        })

        it('is zero without an allocation or a divisor', () => {
            expect(freePrs(inbox({ free_allocation: 0 }))).toBe(0)
            expect(freePrs(inbox({ display_divisor: undefined }))).toBe(0)
            expect(freePrs(null)).toBe(0)
        })
    })
})
