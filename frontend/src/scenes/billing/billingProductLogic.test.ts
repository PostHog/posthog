/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { billingLogic } from 'scenes/billing/billingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingProductV2Type, BillingType, SurveyEventName } from '~/types'

const productByType = (type: string): BillingProductV2Type =>
    billingJson.products.find((p) => p.type === type) as BillingProductV2Type

const seedBilling = async (customLimits: BillingType['custom_limits_usd']): Promise<void> => {
    useMocks({ get: { '/api/billing': () => [200, { ...billingJson, custom_limits_usd: customLimits }] } })
    billingLogic.mount()
    await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
}

describe('billingProductLogic', () => {
    const mounted: ReturnType<typeof billingProductLogic.build>[] = []

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
