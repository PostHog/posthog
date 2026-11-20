/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { billingLogic } from 'lib/logic/billing/billingLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { couponLogic } from './couponLogic'

describe('couponLogic', () => {
    let claimBodies: Record<string, unknown>[]

    beforeEach(async () => {
        initKeaTests()
        claimBodies = []
        useMocks({
            get: {
                '/api/billing': () => [200, { ...billingJson, has_active_subscription: false }],
                '/api/billing/coupons/overview': () => [200, { claimed_coupons: [] }],
            },
            post: {
                '/api/billing/coupons/claim': async ({ request }) => {
                    claimBodies.push((await request.json()) as Record<string, unknown>)
                    return [200, { success: true }]
                },
            },
        })
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
    })

    it('does not send a cheat code submitted on a campaign page as a coupon code', async () => {
        const logic = couponLogic({ campaign: 'every' })
        logic.mount()

        logic.actions.setCouponValue('code', ' HESOYAM ')
        await expectLogic(logic, () => logic.actions.submitCoupon()).toFinishAllListeners()

        expect(claimBodies).toEqual([])
        expect(logic.values.coupon.code).toEqual('')
    })
})
