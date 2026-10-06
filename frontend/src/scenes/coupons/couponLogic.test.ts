/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { billingLogic } from 'scenes/billing/billingLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingType, CouponsOverview } from '~/types'

import { couponLogic } from './couponLogic'

const COUPONS_OVERVIEW: CouponsOverview = {
    claimed_coupons: [
        {
            code: 'EXAMPLE-0000',
            campaign_name: 'Example campaign',
            campaign_slug: 'example',
            claimed_at: '2026-01-01T00:00:00Z',
            expires_at: null,
            status: 'claimed',
        },
    ],
}

describe('couponLogic', () => {
    let overviewRequests = 0
    let answerBilling: () => void = () => {}

    const mockBilling = (billingManagedByPartner: BillingType['billing_managed_by_partner']): void => {
        const billingAnswered = new Promise<void>((resolve) => {
            answerBilling = resolve
        })
        useMocks({
            get: {
                '/api/billing': async () => {
                    await billingAnswered
                    return [200, { ...billingJson, billing_managed_by_partner: billingManagedByPartner }]
                },
                '/api/billing/coupons/overview': () => {
                    overviewRequests += 1
                    return [200, COUPONS_OVERVIEW]
                },
            },
        })
    }

    beforeEach(() => {
        overviewRequests = 0
        initKeaTests()
    })

    it.each([
        { payer: 'the organization', billingManagedByPartner: null, overview: COUPONS_OVERVIEW, requests: 1 },
        {
            payer: 'a partner',
            billingManagedByPartner: { partner_name: 'Example Partner' },
            overview: null,
            requests: 0,
        },
    ])(
        'waits for billing, then reads the coupon overview only when $payer pays',
        async ({ billingManagedByPartner, overview, requests }) => {
            mockBilling(billingManagedByPartner)
            couponLogic.mount()
            billingLogic.actions.loadBilling()

            expect(couponLogic.values.couponsOverviewLoading).toBe(false)
            expect(couponLogic.values.couponsOverview).toBeNull()

            answerBilling()
            await expectLogic(couponLogic).toDispatchActions(['loadBillingSuccess']).toFinishAllListeners()

            expect(overviewRequests).toEqual(requests)
            expect(couponLogic.values.couponsOverview).toEqual(overview)
        }
    )

    it('reads the coupon overview on mount when billing has already loaded', async () => {
        mockBilling(null)
        answerBilling()
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()

        couponLogic.mount()
        await expectLogic(couponLogic).toFinishAllListeners()

        expect(overviewRequests).toEqual(1)
        expect(couponLogic.values.couponsOverview).toEqual(COUPONS_OVERVIEW)
    })
})
