import { expectLogic } from 'kea-test-utils'

import { billingLogic } from 'scenes/billing/billingLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { couponLogic } from './couponLogic'

describe('couponLogic', () => {
    let logic: ReturnType<typeof couponLogic.build>
    let billingRequests: number

    beforeEach(() => {
        billingRequests = 0
        useMocks({
            get: {
                '/api/billing/': () => {
                    billingRequests++
                    return [200, billingJson]
                },
                '/api/billing/coupons/overview': { claimed_coupons: [] },
            },
            post: { '/api/billing/coupons/claim': { success: true } },
        })
        initKeaTests()
        billingLogic.mount()
        logic = couponLogic({ campaign: 'lenny' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    // A claimed coupon can subscribe the org to a package in billing. Without a reload the rest of the
    // app keeps showing the pre-claim state, such as an upsell for a package the org already has.
    it('reloads billing after a successful claim', async () => {
        // Claiming needs billing loaded, since the form requires an active subscription.
        await expectLogic(billingLogic, () => {
            billingLogic.actions.loadBilling()
        })
            .toDispatchActions(['loadBillingSuccess'])
            .toFinishAllListeners()
        const requestsBeforeClaim = billingRequests

        await expectLogic(logic, () => {
            logic.actions.setCouponValue('code', 'LENNY-CODE')
            logic.actions.submitCoupon()
        })
            .toDispatchActions(['submitCouponSuccess'])
            .toFinishAllListeners()

        expect(billingRequests).toBe(requestsBeforeClaim + 1)
    })
})
