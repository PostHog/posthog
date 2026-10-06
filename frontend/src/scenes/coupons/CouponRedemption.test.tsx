/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { billingLogic } from 'scenes/billing/billingLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { campaignConfigs } from './campaigns'
import { CouponRedemption } from './CouponRedemption'

const CAMPAIGN = Object.keys(campaignConfigs)[0]

describe('CouponRedemption', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        { payer: 'the organization', billingManagedByPartner: null, offersClaim: true },
        { payer: 'a partner', billingManagedByPartner: { partner_name: 'Example Partner' }, offersClaim: false },
    ])('offers the claim form: $offersClaim, when $payer pays', async ({ billingManagedByPartner, offersClaim }) => {
        let answerBilling: () => void = () => {}
        const billingAnswered = new Promise<void>((resolve) => {
            answerBilling = resolve
        })
        useMocks({
            get: {
                '/api/billing': async () => {
                    await billingAnswered
                    return [200, { ...billingJson, billing_managed_by_partner: billingManagedByPartner }]
                },
                '/api/billing/coupons/overview': [200, { claimed_coupons: [] }],
            },
        })

        render(
            <Provider>
                <CouponRedemption campaign={CAMPAIGN} />
            </Provider>
        )
        await act(async () => {
            await expectLogic(billingLogic).toDispatchActions(['loadBilling'])
        })

        expect(screen.queryByText('Redeem coupon')).not.toBeInTheDocument()

        answerBilling()
        await act(async () => {
            await expectLogic(billingLogic).toDispatchActions(['loadBillingSuccess']).toFinishAllListeners()
        })

        expect(screen.queryByText('Redeem coupon') !== null).toBe(offersClaim)
        expect(screen.queryByText(/managed by Example Partner/) !== null).toBe(!offersClaim)
    })
})
