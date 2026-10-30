/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { preflightLogic } from 'lib/logic/preflightLogic'
import { billingLogic } from 'scenes/billing/billingLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, BillingProvider, BillingType } from '~/types'

import { payGateMiniLogic } from './payGateMiniLogic'

describe('payGateMiniLogic', () => {
    it.each<{
        name: string
        billing: Partial<BillingType>
        expected: { isPaymentEntryFlow: boolean; ctaDisabledReason: string | null }
    }>([
        {
            name: 'disables the payment entry button when a partner manages billing',
            billing: {
                customer_id: '',
                subscription_level: 'free',
                billing_managed_by_partner: { partner_name: 'Example Partner' },
            },
            expected: {
                isPaymentEntryFlow: true,
                ctaDisabledReason: 'Billing for this organization is managed by Example Partner.',
            },
        },
        {
            name: 'keeps the link to the billing page enabled when a partner manages billing',
            billing: {
                customer_id: '',
                subscription_level: 'paid',
                billing_managed_by_partner: { partner_name: 'Example Partner' },
            },
            expected: { isPaymentEntryFlow: false, ctaDisabledReason: null },
        },
        {
            name: 'disables the payment entry button when Vercel manages billing without an active subscription',
            billing: {
                subscription_level: 'free',
                has_active_subscription: false,
                billing_provider: BillingProvider.Vercel,
            },
            expected: {
                isPaymentEntryFlow: true,
                ctaDisabledReason:
                    'Billing for this organization is managed by Vercel. Contact support to change your plan.',
            },
        },
    ])('$name', async ({ billing, expected }) => {
        useMocks({
            get: {
                '/_preflight': [200, { ...preflightJson, cloud: true }],
                '/api/billing': [200, { ...billingJson, ...billing }],
            },
        })
        initKeaTests()
        await expectLogic(preflightLogic).toFinishAllListeners()
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
        const logic = payGateMiniLogic({ feature: AvailableFeature.SUBSCRIPTIONS })
        logic.mount()

        expect(logic.values).toMatchObject({ gateVariant: 'add-card', ...expected })
    })
})
