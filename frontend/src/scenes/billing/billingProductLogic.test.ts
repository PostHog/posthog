/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'
// Imported from the source module rather than the `@posthog/lemon-ui` barrel so the spy below
// replaces `.error` on the same `lemonToast` singleton the logic calls at runtime (see the same
// note in paymentEntryLogic.test.ts).
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { billingLogic } from 'scenes/billing/billingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { defaultPlatformAddons } from '~/mocks/fixtures/_billing_platform_addons'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingPlan, BillingProductV2AddonType, BillingProductV2Type, BillingType, SurveyEventName } from '~/types'

const productByType = (type: string): BillingProductV2Type =>
    billingJson.products.find((p) => p.type === type) as BillingProductV2Type

describe('billingProductLogic', () => {
    const mounted: ReturnType<typeof billingProductLogic.build>[] = []

    const seedBilling = async (customLimits: BillingType['custom_limits_usd']): Promise<void> => {
        useMocks({ get: { '/api/billing': () => [200, { ...billingJson, custom_limits_usd: customLimits }] } })
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        mounted.forEach((logic) => logic.unmount())
        mounted.length = 0
    })

    const mountProduct = (type: string): ReturnType<typeof billingProductLogic.build> => {
        const logic = billingProductLogic({ product: productByType(type) })
        logic.mount()
        mounted.push(logic)
        return logic
    }

    describe('custom billing limit resolution', () => {
        // $0 is a real, meaningful limit (drop all usage) — it must not be conflated with
        // "no limit set" (unbounded spend). This guards the `=== 0` handling in the
        // customLimitUsd / hasCustomLimitSet selectors.
        it.each([
            ['no custom limit set', {}, null, false],
            ['a positive dollar limit', { product_analytics: 500 }, 500, true],
            ['a $0 limit', { product_analytics: 0 }, 0, true],
            ['a limit set under the usage key', { events: 200 }, 200, true],
        ] as const)('resolves %s', async (_name, customLimits, expectedLimit, expectedHasSet) => {
            await seedBilling(customLimits)
            const logic = mountProduct('product_analytics')

            expect(logic.values.customLimitUsd).toBe(expectedLimit)
            expect(logic.values.hasCustomLimitSet).toBe(expectedHasSet)
        })
    })

    describe('unsubscribe survey state', () => {
        it('keeps survey responses isolated per product type', async () => {
            await seedBilling({})
            const analytics = mountProduct('product_analytics')
            const replay = mountProduct('session_replay')

            analytics.actions.setSurveyResponse('$survey_response', 'analytics feedback')
            analytics.actions.toggleSurveyReason('Too expensive')
            replay.actions.setSurveyResponse('$survey_response', 'replay feedback')

            expect(analytics.values.surveyResponse.$survey_response).toBe('analytics feedback')
            expect(analytics.values.surveyResponse.$survey_response_2).toEqual(['Too expensive'])
            expect(replay.values.surveyResponse.$survey_response).toBe('replay feedback')
            expect(replay.values.surveyResponse.$survey_response_2).toEqual([])
        })

        // Guards the unsubscribe submit path the deleted Playwright spec covered: confirming
        // deactivation must POST the product to /api/billing/deactivate, submit the collected
        // survey on success (deactivateProductSuccess -> reportSurveySent), and clear surveyID so
        // the modal closes. Fake timers step over the loader's real 2s reload breakpoint.
        it('deactivates the product, submits the survey, and clears the modal on confirm', async () => {
            let deactivateBody: any = null
            useMocks({
                get: { '/api/billing': () => [200, billingJson] },
                post: {
                    '/api/billing/deactivate': async ({ request }) => {
                        deactivateBody = await request.json()
                        return [200, billingJson]
                    },
                },
            })
            billingLogic.mount()
            await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()

            const captureSpy = jest.spyOn(posthog, 'capture').mockReturnValue(undefined as any)
            const logic = mountProduct('product_analytics')
            logic.actions.setSurveyID('billing-unsubscribe-survey')
            logic.actions.toggleSurveyReason('Too expensive')
            logic.actions.setSurveyResponse('$survey_response', 'Product analytics')

            jest.useFakeTimers()
            try {
                const expectation = expectLogic(logic, () => {
                    logic.actions.deactivateProduct('product_analytics')
                }).toDispatchActions([
                    'deactivateProduct',
                    'loadBilling',
                    'deactivateProductSuccess',
                    'reportSurveySent',
                    'setSurveyID',
                ])
                // Enough to fire the loader's breakpoint(2000) but not the post-report
                // breakpoint(400), so the jsdom-unsupported scrollIntoView is never reached.
                await jest.advanceTimersByTimeAsync(2100)
                await expectation

                expect(deactivateBody).toEqual({ products: 'product_analytics' })
                expect(captureSpy).toHaveBeenCalledWith(SurveyEventName.SENT, {
                    $survey_id: 'billing-unsubscribe-survey',
                    $survey_response: 'Product analytics',
                    $survey_response_2: ['Too expensive'],
                })
                expect(logic.values.surveyID).toBe('')
            } finally {
                jest.useRealTimers()
                captureSpy.mockRestore()
            }
        })
    })
})

// Scale is a flat-rate platform add-on ($750/mo) — the exact shape that used to charge immediately.
const scaleAddon = defaultPlatformAddons.find((addon) => addon.type === BillingPlan.Scale) as BillingProductV2AddonType

describe('billingProductLogic — confirm purchase modal', () => {
    let logic: ReturnType<typeof billingProductLogic.build>
    let toastErrorSpy: jest.SpyInstance

    const seedBilling = async (billing: Partial<BillingType>): Promise<void> => {
        useMocks({ get: { '/api/billing': () => [200, billing] } })
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
    }

    beforeEach(async () => {
        initKeaTests()
        toastErrorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => ({ id: 'x' }) as any)
        // A card-on-file paying customer is the only one who reaches the flat-rate "Add" button.
        await seedBilling({ customer_id: 'cus_test', subscription_level: 'paid' })
    })

    afterEach(() => {
        logic?.unmount()
        toastErrorSpy.mockRestore()
    })

    it('opens and closes the modal via show/hide actions', async () => {
        logic = billingProductLogic({ product: scaleAddon })
        logic.mount()

        await expectLogic(logic, () => logic.actions.showConfirmPurchaseModal()).toMatchValues({
            confirmPurchaseModalOpen: true,
        })
        await expectLogic(logic, () => logic.actions.hideConfirmPurchaseModal()).toMatchValues({
            confirmPurchaseModalOpen: false,
        })
    })

    it('confirming the purchase activates the add-on with its upgrade plan', async () => {
        // Respond with an error so activation stops before any real-charge side effects, while still
        // proving the request fired with the right add-on + plan.
        const activate = jest.fn(() => [200, { success: false, error: 'stop before charge' }] as [number, unknown])
        useMocks({ post: { '/api/billing/activate': activate } })
        logic = billingProductLogic({ product: scaleAddon })
        logic.mount()

        await expectLogic(logic, () => logic.actions.confirmProductPurchase())
            .toDispatchActions([
                'confirmProductPurchase',
                (a) =>
                    a.type === logic.actionTypes.handleProductUpgrade &&
                    a.payload.products === `${scaleAddon.type}:${scaleAddon.plans[0].plan_key}`,
            ])
            .toFinishAllListeners()

        expect(activate).toHaveBeenCalled()
    })

    it('auto-closes the modal once activation finishes', async () => {
        useMocks({
            post: { '/api/billing/activate': () => [200, { success: false, error: 'x' }] as [number, unknown] },
        })
        logic = billingProductLogic({ product: scaleAddon })
        logic.mount()
        logic.actions.showConfirmPurchaseModal()
        expect(logic.values.confirmPurchaseModalOpen).toBe(true)

        await expectLogic(logic, () => logic.actions.confirmProductPurchase())
            .toFinishAllListeners()
            .toMatchValues({ confirmPurchaseModalOpen: false })
    })

    describe('credit-aware amount selectors', () => {
        // Halfway through a billing period, so the $750 Scale plan prorates to ~$375.
        const seedBillingMidPeriod = async (discountAmountUsd?: string): Promise<void> => {
            await seedBilling({
                customer_id: 'cus_test',
                subscription_level: 'paid',
                products: [],
                discount_amount_usd: discountAmountUsd,
                // Dayjs values serialize to ISO strings in the mocked JSON response, which
                // billingLogic's parseBillingResponse turns back into Dayjs — same as the real API.
                billing_period: {
                    current_period_start: dayjs().subtract(12, 'hour'),
                    current_period_end: dayjs().add(12, 'hour'),
                    interval: 'month',
                },
            })
        }

        it('applies the credit balance against the amount due', async () => {
            await seedBillingMidPeriod('100')
            logic = billingProductLogic({ product: scaleAddon })
            logic.mount()

            expect(logic.values.amountDueBeforeCredits).toBeCloseTo(375, 1)
            expect(logic.values.appliedCreditBalance).toBe(100)
            expect(logic.values.amountDueToday).toBeCloseTo(275, 1)
        })

        it('clamps the amount due at zero when the credit balance exceeds the charge', async () => {
            await seedBillingMidPeriod('1000')
            logic = billingProductLogic({ product: scaleAddon })
            logic.mount()

            // Only the amount due is applied — never more (no negative totals).
            expect(logic.values.appliedCreditBalance).toBeCloseTo(375, 1)
            expect(logic.values.appliedCreditBalance).toBe(logic.values.amountDueBeforeCredits)
            expect(logic.values.amountDueToday).toBe(0)
        })

        it('applies no credit when the customer has no balance', async () => {
            await seedBillingMidPeriod(undefined)
            logic = billingProductLogic({ product: scaleAddon })
            logic.mount()

            expect(logic.values.appliedCreditBalance).toBe(0)
            expect(logic.values.amountDueToday).toBe(logic.values.amountDueBeforeCredits)
        })
    })

    it('does nothing when the product has no upgrade plan', async () => {
        const activate = jest.fn(() => [200, { success: true }] as [number, unknown])
        useMocks({ post: { '/api/billing/activate': activate } })
        const productWithoutPlans = { ...scaleAddon, type: BillingPlan.Boost, plans: [] } as BillingProductV2AddonType
        logic = billingProductLogic({ product: productWithoutPlans })
        logic.mount()

        await expectLogic(logic, () => logic.actions.confirmProductPurchase()).toFinishAllListeners()

        expect(activate).not.toHaveBeenCalled()
    })
})
