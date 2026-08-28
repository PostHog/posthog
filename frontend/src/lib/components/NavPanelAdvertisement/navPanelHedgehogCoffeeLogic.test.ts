import { dayjs } from 'lib/dayjs'

import type { BillingType } from '~/types'

import { donationCampaignKey, donationWindowIndex, isUnderFreeAllowance } from './navPanelHedgehogCoffeeLogic'

function billing(partial: Partial<BillingType>): BillingType {
    return partial as BillingType
}

const NOW = dayjs('2026-08-28')

describe('navPanelHedgehogCoffeeLogic', () => {
    describe('isUnderFreeAllowance', () => {
        it('trusts the backend flag over the client heuristic when present', () => {
            // Backend says no even though products look under allowance - backend wins.
            expect(
                isUnderFreeAllowance(
                    billing({
                        is_under_free_allowance: false,
                        has_active_subscription: false,
                        subscription_level: 'free',
                        products: [],
                    })
                )
            ).toBe(false)
            expect(
                isUnderFreeAllowance(billing({ is_under_free_allowance: true, has_active_subscription: true }))
            ).toBe(true)
        })

        it('is false without a billing payload, so self-hosted never sees the ask', () => {
            expect(isUnderFreeAllowance(null)).toBe(false)
        })

        it.each([
            ['free', { has_active_subscription: false, subscription_level: 'free' as const }, true],
            ['paying', { has_active_subscription: true, subscription_level: 'paid' as const }, false],
            ['custom level', { has_active_subscription: false, subscription_level: 'custom' as const }, false],
        ])('fallback: %s', (_name, partial, expected) => {
            expect(isUnderFreeAllowance(billing({ ...partial, products: [] }))).toBe(expected)
        })

        it('fallback returns false when a product has exceeded its free allocation', () => {
            expect(
                isUnderFreeAllowance(
                    billing({
                        has_active_subscription: false,
                        subscription_level: 'free',
                        products: [{ free_allocation: 1000, current_usage: 1001, has_exceeded_limit: false } as any],
                    })
                )
            ).toBe(false)
        })
    })

    describe('donationWindowIndex', () => {
        it.each([
            ['no creation date', undefined, null],
            ['org two months old', NOW.subtract(2, 'month').toISOString(), null],
            // Window 0 is the org's first six months, so the first ask lands the day it turns six months old.
            ['org five months old', NOW.subtract(5, 'month').toISOString(), null],
            ['org six months old', NOW.subtract(6, 'month').toISOString(), 1],
            ['org eleven months old', NOW.subtract(11, 'month').toISOString(), 1],
            ['org one year old', NOW.subtract(12, 'month').toISOString(), 2],
            ['org three years old', NOW.subtract(36, 'month').toISOString(), 6],
        ])('%s', (_name, createdAt, expected) => {
            expect(donationWindowIndex(createdAt, NOW)).toBe(expected)
        })
    })

    describe('donationCampaignKey', () => {
        it('changes with the window, so a dismissed card comes back six months later', () => {
            expect(donationCampaignKey('org-1', 1)).toBe('hedgehog-coffee-org-1-w1')
            expect(donationCampaignKey('org-1', 2)).not.toBe(donationCampaignKey('org-1', 1))
        })

        it('is scoped per org, so dismissing in one org does not silence another', () => {
            expect(donationCampaignKey('org-2', 1)).not.toBe(donationCampaignKey('org-1', 1))
        })
    })
})
