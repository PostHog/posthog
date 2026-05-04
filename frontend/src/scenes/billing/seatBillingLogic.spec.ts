import { canReactivateSeat, isFreePlanKey, isProPlanKey, seatPriceFromPlanKey } from './seatBillingLogic'

describe('seatBillingLogic plan key helpers', () => {
    describe('isProPlanKey', () => {
        it.each([
            ['posthog-code-pro-200-20260301', true],
            ['posthog-code-pro-0-20260422', true],
            ['posthog-code-pro-500-20270101', true],
            ['posthog-code-free-20260301', false],
            ['posthog-code-200-20260301', false],
            ['some-other-plan', false],
            ['', false],
            [null, false],
            [undefined, false],
        ])('isProPlanKey(%p) === %p', (planKey, expected) => {
            expect(isProPlanKey(planKey)).toBe(expected)
        })
    })

    describe('isFreePlanKey', () => {
        it.each([
            ['posthog-code-free-20260301', true],
            ['posthog-code-free-20270101', true],
            ['posthog-code-pro-200-20260301', false],
            ['posthog-code-pro-0-20260422', false],
            ['some-other-plan', false],
            ['', false],
            [null, false],
            [undefined, false],
        ])('isFreePlanKey(%p) === %p', (planKey, expected) => {
            expect(isFreePlanKey(planKey)).toBe(expected)
        })
    })

    describe('seatPriceFromPlanKey', () => {
        it.each([
            ['posthog-code-pro-200-20260301', 200],
            ['posthog-code-pro-0-20260422', 0],
            ['posthog-code-pro-500-20270101', 500],
            ['posthog-code-free-20260301', 0],
            ['unrecognized-plan', 0],
        ])('seatPriceFromPlanKey(%p) === %p', (planKey, expected) => {
            expect(seatPriceFromPlanKey(planKey)).toBe(expected)
        })
    })

    describe('canReactivateSeat', () => {
        it.each([
            [{ status: 'canceling' as const, plan_key: 'posthog-code-pro-0-20260422' }, false],
            [{ status: 'canceling' as const, plan_key: 'posthog-code-pro-200-20260301' }, true],
            [{ status: 'canceling' as const, plan_key: 'posthog-code-free-20260301' }, true],
            [{ status: 'active' as const, plan_key: 'posthog-code-pro-0-20260422' }, false],
            [null, false],
            [undefined, false],
        ])('canReactivateSeat(%p) === %p', (seat, expected) => {
            expect(canReactivateSeat(seat)).toBe(expected)
        })
    })
})
