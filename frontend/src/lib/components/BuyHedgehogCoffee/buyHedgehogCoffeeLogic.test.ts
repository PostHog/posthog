import { dayjs } from 'lib/dayjs'

import type { BillingType } from '~/types'

import { canShowAgain, isOrgOldEnough, isUnderFreeAllowance } from './buyHedgehogCoffeeLogic'

function billing(partial: Partial<BillingType>): BillingType {
    return partial as BillingType
}

describe('buyHedgehogCoffeeLogic', () => {
    describe('isUnderFreeAllowance', () => {
        it('trusts the backend flag over the client heuristic when present', () => {
            // Backend says no even though products look under allowance — backend wins.
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

    describe('isOrgOldEnough', () => {
        it.each([
            ['undefined', undefined, false],
            ['two months old', dayjs().subtract(2, 'month').toISOString(), false],
            ['seven months old', dayjs().subtract(7, 'month').toISOString(), true],
        ])('%s', (_name, createdAt, expected) => {
            expect(isOrgOldEnough(createdAt)).toBe(expected)
        })
    })

    describe('canShowAgain', () => {
        it.each([
            ['never shown', null, true],
            ['shown two months ago', dayjs().subtract(2, 'month').toISOString(), false],
            ['shown seven months ago', dayjs().subtract(7, 'month').toISOString(), true],
        ])('%s', (_name, lastShownAt, expected) => {
            expect(canShowAgain(lastShownAt)).toBe(expected)
        })
    })
})
